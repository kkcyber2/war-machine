"""
pipeline.py — War Machine Orchestrator
──────────────────────────────────────────────────────────────────────────────
Runs all four stages in sequence:

  Stage 1: Scrape  — Pull fresh leads from YC + Product Hunt
  Stage 2: Enrich  — Generate AI scare hooks via OpenRouter
  Stage 3: Outreach — Send cold emails via Resend
  Stage 4: Report   — Print Shadow Fleet dashboard

Usage:
  python pipeline.py                        # full run
  python pipeline.py --stage scrape         # scrape only
  python pipeline.py --stage outreach       # send emails only
  python pipeline.py --stage report         # dashboard only
  python pipeline.py --dry-run              # full run, no real emails sent
  python pipeline.py --source yc --max 25   # YC only, 25 leads
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("war-machine.pipeline")


def banner() -> None:
    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║    ⚔  FORGEGUARD AI — MARKETING WAR MACHINE  v1.0           ║
║    "They ship AI. We ship breaches."                         ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")


def stage_header(n: int, name: str) -> None:
    print(f"\n{'─'*62}")
    print(f"  STAGE {n}: {name.upper()}")
    print(f"{'─'*62}")


async def run_pipeline(
    source:  str  = "all",
    max_leads: int  = 50,
    dry_run: bool = False,
    stages:  list[str] | None = None,
) -> dict[str, object]:
    """
    Full pipeline orchestrator.
    Returns a summary dict of results per stage.
    """
    banner()
    results: dict[str, object] = {
        "started_at": datetime.utcnow().isoformat(),
        "source":     source,
        "dry_run":    dry_run,
    }

    run_all  = not stages or "all" in stages

    # ── Stage 1: Scrape ───────────────────────────────────────────────────────
    if run_all or "scrape" in (stages or []):
        stage_header(1, "Lead Scraper")
        from scraper import run_scraper
        scraped = await run_scraper(source=source, max_leads=max_leads)
        results["scraped"] = scraped
        logger.info(f"Stage 1 complete: {scraped} leads saved to DB")

    # ── Stage 2: Enrich (scare hooks are generated during outreach) ──────────
    # The ai_brain is called inline in outreach.py — no separate stage needed
    # unless you want to pre-generate hooks without sending emails.
    if "enrich" in (stages or []):
        stage_header(2, "AI Scare Hook Enrichment")
        from db import get_unsent_leads
        from ai_brain import process_leads_batch
        leads  = get_unsent_leads(limit=max_leads)
        logger.info(f"Enriching {len(leads)} leads with scare hooks…")
        leads  = process_leads_batch(leads)
        # Save scare hooks to DB
        from db import get_client
        sb = get_client()
        for lead in leads:
            sb.table("leads").update({
                "scare_hook":   lead.get("scare_hook", ""),
                "vulnerability": lead.get("vulnerability", ""),
                "subject_line": lead.get("subject_line", ""),
            }).eq("id", lead["id"]).execute()
        results["enriched"] = len(leads)
        logger.info(f"Stage 2 complete: {len(leads)} scare hooks generated")

    # ── Stage 3: Outreach ────────────────────────────────────────────────────
    if run_all or "outreach" in (stages or []):
        stage_header(3, "Email Outreach")
        from outreach import run_outreach
        stats = run_outreach(limit=max_leads, dry_run=dry_run)
        results["outreach"] = stats
        logger.info(f"Stage 3 complete: {stats}")

    # ── Stage 4: Dashboard ───────────────────────────────────────────────────
    if run_all or "report" in (stages or []):
        stage_header(4, "Shadow Fleet Dashboard")
        from tracker import print_dashboard, print_recent_activity
        from db import sync_war_machine_stats
        sync_war_machine_stats()
        print_dashboard()
        print_recent_activity(limit=10)

    # Always sync aggregate stats after any pipeline run
    try:
        from db import sync_war_machine_stats
        sync_war_machine_stats()
    except Exception as exc:
        logger.warning("Could not sync war_machine_stats: %s", exc)

    results["finished_at"] = datetime.utcnow().isoformat()
    print(f"\n✅  Pipeline finished at {results['finished_at']}\n")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ForgeGuard War Machine — Full Pipeline")
    parser.add_argument(
        "--stage",
        nargs="+",
        choices=["all", "scrape", "enrich", "outreach", "report"],
        default=["all"],
        help="Which stages to run (default: all)",
    )
    parser.add_argument("--source",  default="all",  choices=["yc", "producthunt", "ph", "all"])
    parser.add_argument("--max",     type=int, default=50, help="Max leads per scraper")
    parser.add_argument("--dry-run", action="store_true",  help="No real emails sent")
    args = parser.parse_args()

    asyncio.run(run_pipeline(
        source=args.source,
        max_leads=args.max,
        dry_run=args.dry_run,
        stages=args.stage,
    ))
