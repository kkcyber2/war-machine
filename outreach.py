"""
outreach.py — Resend cold email, behind the send gate
─────────────────────────────────────────────────────────────────────────────
What changed from v1, and why
─────────────────────────────────────────────────────────────────────────────
v1 built an email for every scraped lead and sent it. Three things were wrong
with that, and all three are fixed here:

1. **It mailed invented addresses.** `guess_email()` produced
   `founder@<their-domain>` for every company, and this module sent to it
   without checking it existed. Now every candidate goes through
   `outreach_policy.evaluate_send()`, which refuses anything whose address was
   not published by its owner.

2. **It asserted findings it never produced.** The old body said "our automated
   recon systems flagged <company>" and stamped a red "VULNERABILITY DETECTED"
   tag on an LLM's guess about a marketing blurb. That is a false statement of
   fact about a named business. The copy now states the *risk class* as a
   hypothesis and explicitly says no test has been run — which is both true and
   a stronger pitch, because it invites verification instead of demanding
   belief.

3. **It used pressure instead of an opt-out.** The Admiral P.S. said the
   platform was "already on our radar" and this was "a courtesy ping before we
   publish the findings" — a threat to publish a security problem unless the
   recipient replied. That is extortionate in tone and, in several
   jurisdictions, unlawful. It is gone. Every message now carries a real
   one-click unsubscribe and a postal address, and both are enforced by the
   gate rather than trusted to the template.

The runner also refuses to start if the suppression list cannot be loaded: a
run that cannot tell who opted out must not send at all.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from config import (
    RESEND_API_KEY,
    FROM_EMAIL,
    FROM_NAME,
    APP_BASE_URL,
    TRACK_BASE_URL,
    EMAIL_DELAY_SECONDS,
    RANK_ADMIRAL,
    RANK_LIEUTENANT,
    RANK_RECRUIT,
    DAILY_SEND_CAP,
    DOMAIN_COOLDOWN_DAYS,
    SEND_WINDOW_START_HOUR,
    SEND_WINDOW_END_HOUR,
    SEND_WEEKENDS,
    POSTAL_ADDRESS,
    UNSUBSCRIBE_BASE_URL,
)
from db import (
    get_unsent_leads,
    mark_emailed,
    get_suppression_lists,
    get_contacted_domains,
    count_sent_since,
)
from ai_brain import generate_scare_hook
from outreach_policy import (
    assert_honest_copy,
    evaluate_send,
    explain,
    normalise_email,
)

logger = logging.getLogger("war-machine.outreach")

RESEND_SEND_URL = "https://api.resend.com/emails"

# ─── Rank-based tone ─────────────────────────────────────────────────────────
# Tone only. No rank gets a different factual claim, and no rank gets a
# pressure line — the difference is how directly the same honest message is
# phrased.

RANK_CONFIG = {
    RANK_ADMIRAL: {
        "salutation": "Admiral",
        "closing":    "Happy to share the checklist we use,",
        "ps_line":    "P.S. If AI security is already covered in-house, reply and I'll close the file — no follow-ups.",
    },
    RANK_LIEUTENANT: {
        "salutation": "Lieutenant",
        "closing":    "Worth a look before your next release,",
        "ps_line":    "P.S. We run a free 72-hour assessment for teams at your stage. Reply 'assess' and I'll send the scope.",
    },
    RANK_RECRUIT: {
        "salutation": "Recruit",
        "closing":    "Ship fast, secure faster,",
        "ps_line":    "P.S. If this isn't relevant, reply 'no' and you won't hear from us again.",
    },
}


# ─── Email template ──────────────────────────────────────────────────────────

def build_email_html(
    company_name:  str,
    founder_name:  str,
    risk_note:     str,
    risk_class:    str,
    rank:          str,
    track_url:     str,
    unsubscribe_url: str,
    postal_address:  str,
) -> tuple[str, str]:
    """Return (html_body, plain_text_body).

    `risk_note` is a *hypothesis* about the risk class, never a claim that a
    test was run. `risk_class` is the category name, shown as a neutral label
    rather than a red "detected" badge.
    """
    cfg        = RANK_CONFIG.get(rank, RANK_CONFIG[RANK_RECRUIT])
    first_name = (founder_name.split()[0] if founder_name else "there")
    salutation = cfg["salutation"]
    closing    = cfg["closing"]
    ps_line    = cfg["ps_line"]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI security risk review — {company_name}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #050505;
      color: #e2e2e2;
      font-family: 'Courier New', Courier, monospace;
      padding: 32px 16px;
    }}
    .container {{
      max-width: 600px;
      margin: 0 auto;
      background: #0d0d0d;
      border: 1px solid rgba(168,85,247,0.15);
      border-radius: 4px;
      overflow: hidden;
    }}
    .header {{
      background: #050505;
      border-bottom: 1px solid rgba(168,85,247,0.12);
      padding: 24px 32px;
    }}
    .logo {{
      font-family: monospace;
      font-size: 11px;
      letter-spacing: 0.2em;
      text-transform: uppercase;
      color: #A855F7;
    }}
    .rank-badge {{
      display: inline-block;
      margin-top: 8px;
      padding: 2px 10px;
      background: rgba(168,85,247,0.08);
      border: 1px solid rgba(168,85,247,0.3);
      color: #A855F7;
      font-size: 9px;
      letter-spacing: 0.2em;
      text-transform: uppercase;
    }}
    .body {{ padding: 32px; }}
    .greeting {{
      font-size: 13px;
      color: #a0a0a0;
      margin-bottom: 20px;
    }}
    .risk-box {{
      background: rgba(168,85,247,0.05);
      border-left: 3px solid #A855F7;
      padding: 16px 20px;
      margin: 20px 0;
      font-size: 13px;
      line-height: 1.7;
      color: #e2e2e2;
    }}
    .risk-tag {{
      display: inline-block;
      padding: 2px 8px;
      background: rgba(168,85,247,0.10);
      border: 1px solid rgba(168,85,247,0.35);
      color: #A855F7;
      font-size: 9px;
      letter-spacing: 0.15em;
      text-transform: uppercase;
      margin-bottom: 10px;
    }}
    .disclaimer {{
      font-size: 11px;
      color: #707070;
      font-style: italic;
      margin-top: 10px;
    }}
    p {{
      font-size: 13px;
      line-height: 1.8;
      color: #c0c0c0;
      margin-bottom: 16px;
    }}
    .cta-btn {{
      display: inline-block;
      margin: 24px 0;
      padding: 14px 32px;
      background: #A855F7;
      color: #050505;
      text-decoration: none;
      font-family: monospace;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      border-radius: 2px;
    }}
    .closing {{
      margin-top: 32px;
      padding-top: 20px;
      border-top: 1px solid rgba(255,255,255,0.05);
      font-size: 12px;
      color: #606060;
    }}
    .ps {{
      margin-top: 16px;
      font-size: 11px;
      color: #505050;
      font-style: italic;
    }}
    .footer {{
      padding: 16px 32px;
      background: #050505;
      border-top: 1px solid rgba(255,255,255,0.04);
      font-size: 10px;
      color: #404040;
      text-align: center;
      line-height: 1.7;
    }}
    .footer a {{ color: #808080; text-decoration: underline; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="logo">⚔ ForgeGuard AI — Security Review</div>
      <div class="rank-badge">Context: {salutation}</div>
    </div>

    <div class="body">
      <div class="greeting">
        &gt;&gt; To: {first_name} // {company_name}<br>
        &gt;&gt; From: ForgeGuard AI<br>
        &gt;&gt; Subject: AI security risk review
      </div>

      <p>{first_name},</p>

      <p>
        I read how <strong>{company_name}</strong> uses AI and wanted to flag one
        risk area worth a look before your next release. This is a hypothesis
        from your public product description — <strong>we have not tested your
        systems</strong>, and I'm not claiming we found anything.
      </p>

      <div class="risk-box">
        <div class="risk-tag">Risk class: {risk_class}</div><br>
        {risk_note}
        <div class="disclaimer">
          Not a finding. No scan, probe or test has been run against {company_name}.
        </div>
      </div>

      <p>
        The reason it's worth ten minutes: this class of issue is usually
        invisible until someone demonstrates it, and by then it's an incident
        rather than a ticket.
      </p>

      <p>
        ForgeGuard runs continuous attack simulation against live AI endpoints —
        prompt injection, resource-exhaustion and data-leakage chains — and
        reports what actually breaks, with reproduction steps.
      </p>

      <a href="{track_url}" class="cta-btn">
        &gt; See what we'd test on {company_name} →
      </a>

      <p>
        If it's already covered in-house, that's a good answer — reply and I'll
        close the file.
      </p>

      <div class="closing">
        {closing}<br><br>
        <strong>ForgeGuard AI</strong><br>
        <a href="{APP_BASE_URL}" style="color:#A855F7;">{APP_BASE_URL}</a>
      </div>

      <div class="ps">{ps_line}</div>
    </div>

    <div class="footer">
      Sent to {company_name} because your team publishes AI-powered products.<br>
      ForgeGuard AI · {postal_address}<br>
      <a href="{unsubscribe_url}">Unsubscribe</a> — one click, no questions, no follow-ups.
    </div>
  </div>
</body>
</html>"""

    plain = f""">> ForgeGuard AI — Security Review
>> To: {first_name} // {company_name}

{first_name},

I read how {company_name} uses AI and wanted to flag one risk area worth a look
before your next release. This is a hypothesis from your public product
description — we have not tested your systems, and I'm not claiming we found
anything.

RISK CLASS: {risk_class}

{risk_note}

(Not a finding. No scan, probe or test has been run against {company_name}.)

This class of issue is usually invisible until someone demonstrates it, and by
then it's an incident rather than a ticket.

ForgeGuard runs continuous attack simulation against live AI endpoints — prompt
injection, resource-exhaustion and data-leakage chains — and reports what
actually breaks, with reproduction steps.

→ See what we'd test: {track_url}

If it's already covered in-house, that's a good answer — reply and I'll close
the file.

{closing}

ForgeGuard AI
{APP_BASE_URL}

---
{ps_line}

---
ForgeGuard AI · {postal_address}
Unsubscribe: {unsubscribe_url}
"""

    return html, plain


# ─── Send via Resend ─────────────────────────────────────────────────────────

def send_email(
    to_email:      str,
    subject:       str,
    html_body:     str,
    plain_body:    str,
    unsubscribe_url: str,
    dry_run:       bool = False,
) -> Optional[str]:
    """Send one email via Resend. Returns the message id, or None on failure.

    `List-Unsubscribe` and `List-Unsubscribe-Post` are set as real headers, not
    just a link in the body: mailbox providers surface a native unsubscribe
    button from them, and a one-click opt-out that actually works is the single
    strongest protection against a spam complaint.
    """
    if dry_run:
        logger.info("[DRY RUN] Would send to: %s\nSubject: %s", to_email, subject)
        return "dry-run-id"

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type":  "application/json",
    }
    payload: dict[str, Any] = {
        "from":    f"{FROM_NAME} <{FROM_EMAIL}>",
        "to":      [to_email],
        "subject": subject,
        "html":    html_body,
        "text":    plain_body,
        "headers": {
            "List-Unsubscribe":      f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
        "tags": [
            {"name": "campaign", "value": "war-machine-v2"},
        ],
    }

    try:
        resp = httpx.post(RESEND_SEND_URL, headers=headers, json=payload, timeout=15.0)
        resp.raise_for_status()
        msg_id = resp.json().get("id")
        logger.info("  ✉  Sent to %s — id=%s", to_email, msg_id)
        return msg_id
    except httpx.HTTPStatusError as e:
        logger.error("  ✗ Resend error %s: %s", e.response.status_code, e.response.text)
        return None
    except Exception as e:
        logger.error("  ✗ Send failed: %s", e)
        return None


# ─── Batch outreach runner ───────────────────────────────────────────────────

def run_outreach(limit: int = 50, dry_run: bool = False) -> dict[str, int]:
    """Gate every candidate, send only what passes, report refusals by reason.

    The returned dict counts sends and every refusal code, so a run that sends
    nothing is diagnosable from its own output instead of looking like a
    silent failure.
    """
    stats: dict[str, int] = {"sent": 0, "skipped": 0, "failed": 0, "held": 0}

    # Load the gate's inputs once per run. If the suppression list cannot be
    # read we stop: sending without knowing who opted out is the one failure
    # mode that cannot be undone.
    try:
        suppressed_emails, suppressed_domains = get_suppression_lists()
        contacted_domains = get_contacted_domains(days=DOMAIN_COOLDOWN_DAYS + 1)
    except Exception as exc:
        logger.error(
            "Refusing to run outreach: could not load suppression/cooldown data (%s). "
            "Sending without it risks mailing people who opted out.",
            exc,
        )
        stats["error"] = 1
        return stats

    day_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    try:
        sent_today = count_sent_since(day_start)
    except Exception as exc:
        logger.error("Refusing to run outreach: could not read today's send count (%s).", exc)
        stats["error"] = 1
        return stats

    leads = get_unsent_leads(limit=limit)
    logger.info("📬  %d candidate leads, %d sent today (cap %d)",
                len(leads), sent_today, DAILY_SEND_CAP)

    for lead in leads:
        decision = evaluate_send(
            lead,
            suppressed_emails=suppressed_emails,
            suppressed_domains=suppressed_domains,
            contacted_domains=contacted_domains,
            sent_today=sent_today,
            daily_cap=DAILY_SEND_CAP,
            cooldown_days=DOMAIN_COOLDOWN_DAYS,
            start_hour=SEND_WINDOW_START_HOUR,
            end_hour=SEND_WINDOW_END_HOUR,
            allow_weekends=SEND_WEEKENDS,
            postal_address=POSTAL_ADDRESS,
            unsubscribe_url=UNSUBSCRIBE_BASE_URL,
        )

        if not decision.allowed:
            logger.info("  %s — %s", explain(decision), lead.get("company_name", "?"))
            stats["held"] += 1
            stats[decision.code] = stats.get(decision.code, 0) + 1
            continue

        email = normalise_email(lead.get("email"))

        # Generate the risk note if the lead has none stored.
        if not lead.get("scare_hook"):
            hook = generate_scare_hook(
                company_name=lead["company_name"],
                description=lead.get("description", ""),
                rank=lead.get("rank", RANK_RECRUIT),
            )
            risk_note  = hook["scare_hook"]
            subject    = hook["subject_line"]
            risk_class = hook["vulnerability"]
        else:
            risk_note  = lead["scare_hook"]
            subject    = lead.get("subject_line") or f"AI security risk review — {lead['company_name']}"
            risk_class = lead.get("vulnerability") or "AI security risk"

        click_token = lead.get("click_token", "")
        track_url   = f"{TRACK_BASE_URL}/{click_token}" if click_token else APP_BASE_URL
        # Per-recipient unsubscribe so an opt-out identifies the exact lead.
        unsubscribe_url = (
            f"{UNSUBSCRIBE_BASE_URL}?token={click_token}" if click_token else UNSUBSCRIBE_BASE_URL
        )

        html_body, plain_body = build_email_html(
            company_name=lead["company_name"],
            founder_name=lead.get("founder_name", ""),
            risk_note=risk_note,
            risk_class=risk_class,
            rank=lead.get("rank", RANK_RECRUIT),
            track_url=track_url,
            unsubscribe_url=unsubscribe_url,
            postal_address=POSTAL_ADDRESS,
        )

        # Last line of defence: if a template edit reintroduces a fabricated
        # finding, the send is refused rather than delivered.
        violations = assert_honest_copy(html_body) + assert_honest_copy(plain_body)
        if violations:
            logger.error(
                "  ✗ Copy check failed for %s — refusing to send. Offending phrases: %s",
                lead["company_name"], "; ".join(violations),
            )
            stats["held"] += 1
            stats["copy_violation"] = stats.get("copy_violation", 0) + 1
            continue

        msg_id = send_email(
            to_email=email,
            subject=subject,
            html_body=html_body,
            plain_body=plain_body,
            unsubscribe_url=unsubscribe_url,
            dry_run=dry_run,
        )

        if msg_id:
            mark_emailed(lead_id=lead["id"], scare_hook=risk_note, resend_msg_id=msg_id)
            stats["sent"] += 1
            sent_today += 1
            # Record the domain immediately so a second lead at the same
            # company in this same run is caught by the cooldown.
            from outreach_policy import domain_key
            key = domain_key(email)
            if key:
                contacted_domains.append(f"{key}|{datetime.now(timezone.utc).isoformat()}")
        else:
            stats["failed"] += 1

        time.sleep(EMAIL_DELAY_SECONDS)

    logger.info("✅  Outreach complete: %s", stats)
    return stats


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
    parser = argparse.ArgumentParser(description="ForgeGuard War Machine — Email Outreach")
    parser.add_argument("--limit",   type=int,  default=50)
    parser.add_argument("--dry-run", action="store_true", help="Print emails instead of sending")
    args = parser.parse_args()
    run_outreach(limit=args.limit, dry_run=args.dry_run)
