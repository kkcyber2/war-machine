"""
db.py — Supabase client + leads table helpers
──────────────────────────────────────────────────────────────────────────────
All DB interactions go through this module. Uses the service role key so it
bypasses RLS — run server-side only, never expose this client to a browser.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY

logger = logging.getLogger("war-machine.db")

# ─── Singleton client ────────────────────────────────────────────────────────

_client: Optional[Client] = None

def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _client


# ─── Lead helpers ────────────────────────────────────────────────────────────

# Columns present on live ForgeGuard Supabase `public.leads` (nlginrukltrwpkyujzzx)
LEAD_UPSERT_FIELDS = frozenset({
    "company_name",
    "website_url",
    "founder_name",
    "description",
    "vulnerability_summary",
    "source",
    "rank",
    "status",
    "email",
    # Where the address came from. Without this column the gate cannot tell a
    # published mailbox from the founder@<domain> addresses the old scraper
    # invented, so it is part of the upsert rather than optional metadata.
    "contact_source",
})

def _drop_unverified_contacts(payload: dict[str, Any]) -> dict[str, Any]:
    """Never persist an address that did not come from a published source.

    Defence in depth: even if a caller hands us `email` with a missing or
    synthetic `contact_source`, the row is stored without the address instead
    of storing a guess that a later run would mail. A lead with no address is
    still a valid lead for the dashboard; a wrong address is a complaint.
    """
    from outreach_policy import SENDABLE_CONTACT_SOURCES, normalise_email

    source = str(payload.get("contact_source") or "").strip().lower()
    if source not in SENDABLE_CONTACT_SOURCES:
        payload.pop("email", None)
        payload["contact_source"] = ""
        return payload

    email = normalise_email(payload.get("email"))
    if not email:
        payload.pop("email", None)
        payload["contact_source"] = ""
        return payload

    payload["email"] = email
    payload["contact_source"] = source
    return payload


def upsert_lead(lead: dict[str, Any]) -> dict[str, Any]:
    """
    Insert a lead or update it if the website_url already exists.
    Returns the full row including the auto-generated id + click_token.
    """
    payload = {k: v for k, v in lead.items() if k in LEAD_UPSERT_FIELDS}
    if not payload.get("company_name"):
        raise ValueError("company_name is required")
    payload = _drop_unverified_contacts(payload)
    sb = get_client()
    result = (
        sb.table("leads")
        .upsert(payload, on_conflict="website_url")
        .execute()
    )
    if result.data:
        return result.data[0]
    raise RuntimeError(f"upsert_lead failed: {result}")


def get_unsent_leads(limit: int = 50) -> list[dict[str, Any]]:
    """Candidates for outreach: status 'new', with an address, not yet mailed.

    This is only a *candidate* list. The old version treated it as the send
    list, which is why a lead reset to 'new' by a migration went straight back
    out the door. outreach.py decides; this just narrows the query so the gate
    is not run over every historical row.

    `emailed_at IS NULL` is checked here as well as in the gate because it cuts
    the result set at the database instead of in memory.
    """
    sb = get_client()
    result = (
        sb.table("leads")
        .select("*")
        .eq("status", "new")
        .not_.is_("email", "null")
        .is_("emailed_at", "null")
        .limit(limit)
        .execute()
    )
    return result.data or []


def mark_emailed(lead_id: str, scare_hook: str, resend_msg_id: str = "") -> None:
    """Mark a lead as emailed, store the hook used and the provider message id.

    The message id is what makes a bounce or complaint webhook traceable back
    to a specific send; without it, suppressing the offender later means
    guessing from timestamps.
    """
    sb = get_client()
    payload: dict[str, Any] = {
        "status":     "emailed",
        "scare_hook": scare_hook,
        "emailed_at": datetime.now(timezone.utc).isoformat(),
    }
    if resend_msg_id:
        payload["resend_msg_id"] = resend_msg_id
    sb.table("leads").update(payload).eq("id", lead_id).execute()


# ─── Gate inputs ─────────────────────────────────────────────────────────────

def get_suppression_lists() -> tuple[set[str], set[str]]:
    """Addresses and domains that must never be mailed again.

    Any lead whose terminal status is unsubscribed, bounced, clicked-and-
    replied, or converted has told us something final about whether they want
    mail. Their address *and* their whole domain go on the block list, because
    mailing a colleague after one person opted out is exactly the behaviour
    that gets a sender reported.
    """
    sb = get_client()
    blocked_emails: set[str] = set()
    blocked_domains: set[str] = set()
    try:
        rows = (
            sb.table("leads")
            .select("email,website_url,status")
            .in_("status", ["unsubscribed", "bounced", "responded"])
            .execute()
            .data or []
        )
    except Exception as exc:
        logger.error("Could not load suppression list: %s", exc)
        # Failing closed would stop all outreach; failing open would mail
        # people who opted out. Returning nothing here means the run refuses
        # every candidate for another reason (see outreach.run_outreach), so
        # this is a loud warning rather than a silent allow.
        raise

    from outreach_policy import domain_key, normalise_email

    for row in rows:
        email = normalise_email(row.get("email"))
        if email:
            blocked_emails.add(email)
        key = domain_key(email) if email else ""
        if key:
            blocked_domains.add(key)
        website = str(row.get("website_url") or "")
        if website:
            host = website.split("//")[-1].split("/")[0]
            website_key = domain_key(host)
            if website_key:
                blocked_domains.add(website_key)
    return blocked_emails, blocked_domains


def get_contacted_domains(days: int = 365) -> list[str]:
    """`domain|emailed_at` for every recent send, newest first.

    Used for the per-domain cooldown. Returned as compact strings so the gate
    stays free of database types.
    """
    sb = get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        rows = (
            sb.table("leads")
            .select("email,website_url,emailed_at")
            .not_.is_("emailed_at", "null")
            .gte("emailed_at", cutoff)
            .execute()
            .data or []
        )
    except Exception as exc:
        logger.error("Could not load contacted domains: %s", exc)
        raise

    from outreach_policy import domain_key, normalise_email

    entries: list[str] = []
    for row in rows:
        stamp = row.get("emailed_at") or ""
        email = normalise_email(row.get("email"))
        key = domain_key(email) if email else domain_key(str(row.get("website_url") or ""))
        if key:
            entries.append(f"{key}|{stamp}")
    return entries


def count_sent_since(since_iso: str) -> int:
    """How many messages have gone out since `since_iso` — the daily cap input."""
    sb = get_client()
    rows = (
        sb.table("leads")
        .select("id")
        .not_.is_("emailed_at", "null")
        .gte("emailed_at", since_iso)
        .execute()
        .data or []
    )
    return len(rows)


def mark_clicked(click_token: str) -> Optional[dict[str, Any]]:
    """
    Called by the tracking API route when a lead clicks the link.
    Returns the updated lead row.
    """
    sb = get_client()
    result = (
        sb.table("leads")
        .update({"status": "clicked", "clicked_at": "now()"})
        .eq("click_token", click_token)
        .execute()
    )
    return result.data[0] if result.data else None


def mark_responded(lead_id: str) -> None:
    """Mark a lead as responded (manually triggered)."""
    sb = get_client()
    sb.table("leads").update({"status": "responded"}).eq("id", lead_id).execute()


def get_pipeline_stats() -> dict[str, int]:
    """Return counts for each status — used by the Shadow Fleet dashboard."""
    sb    = get_client()
    rows  = sb.table("leads").select("status").execute().data or []
    stats: dict[str, int] = {}
    for row in rows:
        s = row.get("status", "unknown")
        stats[s] = stats.get(s, 0) + 1
    return stats


def sync_war_machine_stats() -> dict[str, int]:
    """
    Roll up leads table counts into war_machine_stats (single-row aggregate).
    Returns the synced totals.
    """
    sb = get_client()
    rows = sb.table("leads").select("status").execute().data or []

    total_scraped = len(rows)
    total_emailed = sum(
        1 for r in rows if r.get("status") in ("emailed", "clicked", "responded", "converted")
    )
    total_clicks = sum(
        1 for r in rows if r.get("status") in ("clicked", "responded", "converted")
    )

    existing = sb.table("war_machine_stats").select("id").limit(1).execute().data or []
    payload = {
        "total_scraped": total_scraped,
        "total_emailed": total_emailed,
        "total_clicks": total_clicks,
        "updated_at": "now()",
    }

    if existing:
        sb.table("war_machine_stats").update(payload).eq("id", existing[0]["id"]).execute()
    else:
        sb.table("war_machine_stats").insert(payload).execute()

    return {
        "total_scraped": total_scraped,
        "total_emailed": total_emailed,
        "total_clicks": total_clicks,
    }


def get_war_machine_stats() -> dict[str, int]:
    """Fetch aggregate stats row for dashboard KPIs."""
    sb = get_client()
    rows = sb.table("war_machine_stats").select("*").limit(1).execute().data or []
    if not rows:
        return sync_war_machine_stats()
    row = rows[0]
    return {
        "total_scraped": int(row.get("total_scraped") or 0),
        "total_emailed": int(row.get("total_emailed") or 0),
        "total_clicks": int(row.get("total_clicks") or 0),
    }
