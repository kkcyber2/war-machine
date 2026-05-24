"""
tracker.py — Shadow Fleet Dashboard
──────────────────────────────────────────────────────────────────────────────
Python-side tracking logic and CLI dashboard.

The actual click capture happens in the Next.js API route:
  src/app/api/track/[token]/route.ts
which calls Supabase directly and then redirects to forgeguard.ai.

This module provides:
  1. CLI dashboard — prints pipeline stats
  2. webhook_handler — process click events from the Next.js route
     (if you want a standalone Python webhook server instead)
  3. Export to CSV for manual CRM import

Usage:
  python tracker.py --dashboard       # print live stats
  python tracker.py --export leads.csv
"""

from __future__ import annotations

import csv
import logging
import os
import sys
from datetime import datetime
from typing import Optional

import httpx
from db import get_client, get_pipeline_stats, mark_clicked

logger = logging.getLogger("war-machine.tracker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")


# ─── Dashboard ────────────────────────────────────────────────────────────────

STATUS_ICONS = {
    "new":       "⬜",
    "emailed":   "📨",
    "clicked":   "🟢",
    "responded": "⭐",
    "converted": "💰",
    "bounced":   "❌",
}

def print_dashboard() -> None:
    """Print a terminal-friendly Shadow Fleet pipeline overview."""
    stats = get_pipeline_stats()
    total = sum(stats.values())

    print("\n" + "═" * 52)
    print("  ⚔  FORGEGUARD WAR MACHINE — SHADOW FLEET DASHBOARD")
    print("═" * 52)
    print(f"  {'STATUS':<14}  {'COUNT':>6}  {'%':>6}  BAR")
    print("─" * 52)

    order = ["new", "emailed", "clicked", "responded", "converted", "bounced"]
    for status in order + [s for s in stats if s not in order]:
        count = stats.get(status, 0)
        if count == 0 and status not in ("clicked", "responded", "converted"):
            continue
        pct   = (count / total * 100) if total else 0
        bar   = "█" * int(pct / 4)
        icon  = STATUS_ICONS.get(status, "  ")
        print(f"  {icon} {status:<12}  {count:>6}  {pct:>5.1f}%  {bar}")

    print("─" * 52)
    print(f"  {'TOTAL':<14}  {total:>6}")
    print("═" * 52)

    # Conversion funnel
    emailed   = stats.get("emailed", 0) + stats.get("clicked", 0) + stats.get("responded", 0) + stats.get("converted", 0)
    clicked   = stats.get("clicked", 0) + stats.get("responded", 0) + stats.get("converted", 0)
    responded = stats.get("responded", 0) + stats.get("converted", 0)

    if emailed:
        ctr = clicked / emailed * 100
        rtr = responded / emailed * 100
        print(f"\n  CTR (clicked/emailed):    {ctr:.1f}%")
        print(f"  Reply rate (resp/emailed): {rtr:.1f}%")

    print()


# ─── Webhook handler (optional standalone) ────────────────────────────────────

def handle_click_webhook(click_token: str, ip: str = "", ua: str = "") -> dict:
    """
    Called when a tracked link is clicked.
    Updates the lead status to 'clicked' in Supabase.
    Returns the updated lead row or an error dict.
    """
    if not click_token:
        return {"ok": False, "error": "missing click_token"}

    lead = mark_clicked(click_token)
    if not lead:
        logger.warning(f"No lead found for click_token={click_token}")
        return {"ok": False, "error": "token_not_found"}

    logger.info(f"🟢 Click tracked: {lead.get('company_name')} ({click_token[:8]}…)")
    return {
        "ok":           True,
        "company_name": lead.get("company_name"),
        "status":       lead.get("status"),
        "redirect_url": os.getenv("APP_BASE_URL", "https://forgeguard.ai"),
    }


# ─── CSV export ───────────────────────────────────────────────────────────────

def export_to_csv(output_path: str) -> int:
    """Export all leads to a CSV file for CRM import."""
    sb   = get_client()
    rows = sb.table("leads").select("*").order("created_at", desc=True).execute().data or []

    if not rows:
        logger.warning("No leads to export.")
        return 0

    fields = [
        "id", "company_name", "website_url", "founder_name", "email",
        "description", "source", "batch", "rank", "status",
        "scare_hook", "vulnerability", "click_token",
        "created_at", "emailed_at", "clicked_at",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"✅  Exported {len(rows)} leads to {output_path}")
    return len(rows)


# ─── Recent activity ─────────────────────────────────────────────────────────

def print_recent_activity(limit: int = 20) -> None:
    """Show the most recently active leads."""
    sb   = get_client()
    rows = (
        sb.table("leads")
        .select("company_name, email, status, rank, emailed_at, clicked_at")
        .order("emailed_at", desc=True)
        .limit(limit)
        .execute()
        .data or []
    )

    print(f"\n{'COMPANY':<30} {'STATUS':<12} {'RANK':<12} {'EMAILED':<20} {'CLICKED'}")
    print("─" * 90)
    for row in rows:
        name    = (row.get("company_name") or "")[:28]
        status  = (row.get("status") or "new")
        rank    = (row.get("rank") or "Recruit")
        emailed = (row.get("emailed_at") or "")[:16]
        clicked = (row.get("clicked_at") or "—")[:16]
        icon    = STATUS_ICONS.get(status, "  ")
        print(f"{name:<30} {icon} {status:<10} {rank:<12} {emailed:<20} {clicked}")


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Shadow Fleet Dashboard")
    parser.add_argument("--dashboard",    action="store_true", help="Print pipeline stats")
    parser.add_argument("--recent",       action="store_true", help="Print recent activity")
    parser.add_argument("--export",       metavar="FILE",      help="Export leads to CSV")
    parser.add_argument("--click-token",  metavar="TOKEN",     help="Manually record a click")
    args = parser.parse_args()

    if args.dashboard or not any(vars(args).values()):
        print_dashboard()
    if args.recent:
        print_recent_activity()
    if args.export:
        export_to_csv(args.export)
    if args.click_token:
        result = handle_click_webhook(args.click_token)
        print(result)
