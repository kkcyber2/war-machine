"""
outreach.py — Resend Cold Email Outreach
──────────────────────────────────────────────────────────────────────────────
Sends personalized cold emails using the Resend API.
Each email is rank-branded (Admiral / Lieutenant / Recruit) and includes:
  - Dynamic subject line from the AI scare hook
  - Personalized opening with company name + vulnerability
  - Marineford-flavored CTA to forgeguard.ai
  - Unique tracking link (click_token → forgeguard.ai/api/track/{token})
  - Plain text + HTML multipart for deliverability
"""

from __future__ import annotations

import logging
import time
from typing import Optional

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
)
from db import get_unsent_leads, mark_emailed
from ai_brain import generate_scare_hook

logger = logging.getLogger("war-machine.outreach")

RESEND_SEND_URL = "https://api.resend.com/emails"

# ─── Rank-based tone configs ──────────────────────────────────────────────────

RANK_CONFIG = {
    RANK_ADMIRAL: {
        "salutation": "Admiral",
        "opener_tone": "direct",
        "closing":     "Awaiting your orders,",
        "ps_line":     "P.S. Your platform is already on our radar. This is a courtesy ping before we publish the findings.",
    },
    RANK_LIEUTENANT: {
        "salutation": "Lieutenant",
        "opener_tone": "urgent",
        "closing":     "Locked and loaded,",
        "ps_line":     "P.S. We're running a free 72-hour recon window for scaling startups. Slots are limited.",
    },
    RANK_RECRUIT: {
        "salutation": "Recruit",
        "opener_tone": "sharp",
        "closing":     "Stay frosty,",
        "ps_line":     "P.S. Ship fast, secure faster. We built this for founders who move at your speed.",
    },
}


# ─── Email template ───────────────────────────────────────────────────────────

def build_email_html(
    company_name:  str,
    founder_name:  str,
    scare_hook:    str,
    vulnerability: str,
    rank:          str,
    track_url:     str,
) -> tuple[str, str]:
    """
    Returns (html_body, plain_text_body).
    """
    cfg         = RANK_CONFIG.get(rank, RANK_CONFIG[RANK_RECRUIT])
    first_name  = (founder_name.split()[0] if founder_name else "Founder")
    salutation  = cfg["salutation"]
    closing     = cfg["closing"]
    ps_line     = cfg["ps_line"]
    cta_url     = track_url

    # ── HTML ──────────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ForgeGuard AI Security Alert</title>
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
    .body {{
      padding: 32px;
    }}
    .greeting {{
      font-size: 13px;
      color: #a0a0a0;
      margin-bottom: 20px;
    }}
    .alert-box {{
      background: rgba(239,68,68,0.06);
      border-left: 3px solid #ef4444;
      padding: 16px 20px;
      margin: 20px 0;
      font-size: 13px;
      line-height: 1.7;
      color: #e2e2e2;
    }}
    .vuln-tag {{
      display: inline-block;
      padding: 2px 8px;
      background: rgba(239,68,68,0.12);
      border: 1px solid rgba(239,68,68,0.4);
      color: #ef4444;
      font-size: 9px;
      letter-spacing: 0.15em;
      text-transform: uppercase;
      margin-bottom: 10px;
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
    }}
    .footer a {{ color: #606060; text-decoration: none; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="logo">⚔ ForgeGuard AI — Recon Division</div>
      <div class="rank-badge">Clearance Level: {salutation}</div>
    </div>

    <div class="body">
      <div class="greeting">
        &gt;&gt; To: {first_name} // {company_name}<br>
        &gt;&gt; From: ForgeGuard AI Red Team<br>
        &gt;&gt; Classification: CONFIDENTIAL — AI SECURITY ASSESSMENT
      </div>

      <p>
        {first_name},
      </p>

      <p>
        Our automated recon systems flagged <strong>{company_name}</strong> while
        scanning the AI threat landscape. What we found warrants a direct line.
      </p>

      <div class="alert-box">
        <div class="vuln-tag">⚠ {vulnerability}</div><br>
        {scare_hook}
      </div>

      <p>
        Most founders discover this when it's already a breach, not a warning.
        ForgeGuard AI runs the exact attack simulation your red team should be running —
        automated, continuous, and built specifically for AI-native products.
      </p>

      <p>
        We're talking <strong>prompt injection probes, EDoS simulations, and
        data-leakage attack chains</strong> — the full arsenal, run against your
        live endpoints with zero friction.
      </p>

      <a href="{cta_url}" class="cta-btn">
        &gt; Deploy ForgeGuard on {company_name} →
      </a>

      <p>
        Takes 5 minutes to set up. The first report will tell you more about
        your AI attack surface than a week of manual testing.
      </p>

      <div class="closing">
        {closing}<br><br>
        <strong>ForgeGuard AI — Recon Division</strong><br>
        <a href="{APP_BASE_URL}" style="color:#A855F7;">{APP_BASE_URL}</a>
      </div>

      <div class="ps">{ps_line}</div>
    </div>

    <div class="footer">
      You're receiving this because {company_name} is an AI-native startup
      in our threat intelligence database. Not relevant?
      <a href="{APP_BASE_URL}/unsubscribe">Unsubscribe</a>
    </div>
  </div>
</body>
</html>"""

    # ── Plain text ─────────────────────────────────────────────────────────────
    plain = f""">> ForgeGuard AI — Recon Division
>> Clearance Level: {salutation}
>> To: {first_name} // {company_name}
>> Classification: CONFIDENTIAL

{first_name},

Our automated recon systems flagged {company_name} while scanning the AI threat landscape.

[!] VULNERABILITY DETECTED: {vulnerability}

{scare_hook}

Most founders discover this when it's already a breach.

ForgeGuard AI runs automated red-team simulations against your live AI endpoints —
prompt injection probes, EDoS chains, and data-leakage attacks — in 5 minutes flat.

→ Deploy ForgeGuard now: {cta_url}

{closing}

ForgeGuard AI — Recon Division
{APP_BASE_URL}

---
{ps_line}

---
Unsubscribe: {APP_BASE_URL}/unsubscribe
"""

    return html, plain


# ─── Send via Resend ──────────────────────────────────────────────────────────

def send_email(
    to_email:      str,
    subject:       str,
    html_body:     str,
    plain_body:    str,
    dry_run:       bool = False,
) -> Optional[str]:
    """
    Send an email via Resend API.
    Returns the Resend message ID on success, None on failure.
    Set dry_run=True to print instead of sending (for testing).
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would send to: {to_email}\nSubject: {subject}")
        return "dry-run-id"

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type":  "application/json",
    }
    payload = {
        "from":    f"{FROM_NAME} <{FROM_EMAIL}>",
        "to":      [to_email],
        "subject": subject,
        "html":    html_body,
        "text":    plain_body,
        "tags": [
            {"name": "campaign", "value": "war-machine-v1"},
        ],
    }

    try:
        resp = httpx.post(RESEND_SEND_URL, headers=headers, json=payload, timeout=15.0)
        resp.raise_for_status()
        msg_id = resp.json().get("id")
        logger.info(f"  ✉  Sent to {to_email} — id={msg_id}")
        return msg_id
    except httpx.HTTPStatusError as e:
        logger.error(f"  ✗ Resend error {e.response.status_code}: {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"  ✗ Send failed: {e}")
        return None


# ─── Batch outreach runner ────────────────────────────────────────────────────

def run_outreach(limit: int = 50, dry_run: bool = False) -> dict[str, int]:
    """
    Fetch unsent leads → generate scare hooks → send emails → mark emailed.
    Returns stats dict.
    """
    stats = {"sent": 0, "skipped": 0, "failed": 0}

    leads = get_unsent_leads(limit=limit)
    logger.info(f"📬  Processing {len(leads)} unsent leads…")

    for lead in leads:
        email = lead.get("email", "").strip()
        if not email or "@" not in email:
            logger.warning(f"  ⚠  No email for {lead['company_name']} — skipping")
            stats["skipped"] += 1
            continue

        # Generate scare hook if not already stored
        if not lead.get("scare_hook"):
            hook = generate_scare_hook(
                company_name=lead["company_name"],
                description=lead.get("description", ""),
            )
            scare_hook    = hook["scare_hook"]
            subject_line  = hook["subject_line"]
            vulnerability = hook["vulnerability"]
        else:
            scare_hook    = lead["scare_hook"]
            subject_line  = f"AI security alert for {lead['company_name']}"
            vulnerability = "AI Vulnerability"

        # Build tracking URL
        click_token = lead.get("click_token", "")
        track_url   = f"{TRACK_BASE_URL}/{click_token}" if click_token else APP_BASE_URL

        # Build email bodies
        html_body, plain_body = build_email_html(
            company_name=lead["company_name"],
            founder_name=lead.get("founder_name", ""),
            scare_hook=scare_hook,
            vulnerability=vulnerability,
            rank=lead.get("rank", RANK_RECRUIT),
            track_url=track_url,
        )

        # Send
        msg_id = send_email(
            to_email=email,
            subject=subject_line,
            html_body=html_body,
            plain_body=plain_body,
            dry_run=dry_run,
        )

        if msg_id:
            mark_emailed(lead_id=lead["id"], scare_hook=scare_hook)
            stats["sent"] += 1
        else:
            stats["failed"] += 1

        time.sleep(EMAIL_DELAY_SECONDS)

    logger.info(f"\n✅  Outreach complete: {stats}")
    return stats


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
    parser = argparse.ArgumentParser(description="ForgeGuard War Machine — Email Outreach")
    parser.add_argument("--limit",   type=int,  default=50)
    parser.add_argument("--dry-run", action="store_true", help="Print emails instead of sending")
    args = parser.parse_args()
    run_outreach(limit=args.limit, dry_run=args.dry_run)
