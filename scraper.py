"""
scraper.py — Lead Scraper (v2)
──────────────────────────────────────────────────────────────────────────────
Targets:
  1. Y Combinator Startup Directory  (ycombinator.com/companies)
  2. Product Hunt AI Category        (producthunt.com/topics/artificial-intelligence)

Improvements over v1:
  - wait_until="domcontentloaded" + explicit network-idle wait helper
  - Retry scroll loop with stagnation detection
  - Broader CSS selector fallback chains
  - Per-scraper timeout isolation (one site failing won't kill the run)

Usage:
  python scraper.py --source yc --max 50
  python scraper.py --source producthunt --max 30
  python scraper.py --source all
"""

from __future__ import annotations

import asyncio
import argparse
import logging
import re
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PWTimeout
from db import upsert_lead
from config import MAX_LEADS_PER_RUN, HEADLESS, SCRAPE_DELAY_SECONDS

logger = logging.getLogger("war-machine.scraper")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")


# ── Helpers ───────────────────────────────────────────────────────────────────

def clean(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def infer_rank(description: str, batch: str = "") -> str:
    desc = (description + " " + batch).lower()
    if any(k in desc for k in ["series a", "series b", "series c", "ipo", "$10m", "$20m", "$50m", "raised $"]):
        return "Admiral"
    if any(k in desc for k in ["seed", "pre-series", "$1m", "$2m", "$3m", "$5m", "launched", "yc"]):
        return "Lieutenant"
    return "Recruit"


async def _wait_for_content(page: Page, delay: float = 1.5) -> None:
    """Wait for network to quiet down, then a short buffer."""
    try:
        await page.wait_for_load_state("networkidle", timeout=10_000)
    except PWTimeout:
        pass
    await asyncio.sleep(delay)


async def _scroll_to_bottom(page: Page, max_scrolls: int = 15, stagnation_limit: int = 3) -> None:
    """Scroll until no new content loads."""
    prev_height = 0
    stagnant = 0
    for _ in range(max_scrolls):
        height = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(SCRAPE_DELAY_SECONDS)
        new_height = await page.evaluate("document.body.scrollHeight")
        if new_height == prev_height:
            stagnant += 1
            if stagnant >= stagnation_limit:
                break
        else:
            stagnant = 0
        prev_height = new_height


# ── YC Scraper ────────────────────────────────────────────────────────────────

YC_LIST_URL = "https://www.ycombinator.com/companies?query=ai+security"

# Card selector — YC uses hashed class names; we try multiple patterns
YC_CARD_SELECTORS = [
    "a[href^='/companies/']",
    "a[class*='_company_']",
    ".company-card a",
]

async def scrape_yc(page: Page, max_leads: int) -> list[dict]:
    logger.info("🔍 YC — navigating to company directory…")
    leads: list[dict] = []

    await page.goto(YC_LIST_URL, wait_until="domcontentloaded", timeout=60_000)
    await _wait_for_content(page)

    # Scroll to load more cards
    await _scroll_to_bottom(page, max_scrolls=20)

    # Try selector fallback chain
    cards = []
    for sel in YC_CARD_SELECTORS:
        cards = await page.query_selector_all(sel)
        if cards:
            logger.info(f"  YC selector hit: '{sel}' → {len(cards)} cards")
            break

    if not cards:
        logger.warning("  YC: no cards found with any selector")
        return leads

    # Deduplicate hrefs
    seen: set[str] = set()
    unique_cards = []
    for card in cards:
        href = (await card.get_attribute("href") or "").strip()
        if href and href not in seen:
            seen.add(href)
            unique_cards.append((card, href))

    logger.info(f"  YC: {len(unique_cards)} unique company cards")

    for card, href in unique_cards[:max_leads]:
        try:
            # Extract inline data from card
            name_el = await card.query_selector(
                "[class*='coName'], [class*='name'], h3, strong"
            )
            desc_el = await card.query_selector(
                "[class*='coDescription'], [class*='description'], [class*='tagline'], p"
            )

            company_name = clean(await name_el.inner_text() if name_el else "")
            description  = clean(await desc_el.inner_text() if desc_el else "")
            yc_url = f"https://www.ycombinator.com{href}" if href.startswith("/") else href

            if not company_name:
                continue

            # Visit company page for enrichment
            website_url  = ""
            founder_name = ""
            batch        = ""

            try:
                await page.goto(yc_url, wait_until="domcontentloaded", timeout=30_000)
                await _wait_for_content(page, delay=0.8)

                # Website — look for external link in header area
                for link_sel in ['a[rel~="nofollow"][href^="http"]', 'a[class*="website"]', 'a[target="_blank"][href^="http"]']:
                    link_el = await page.query_selector(link_sel)
                    if link_el:
                        candidate = clean(await link_el.get_attribute("href") or "")
                        if "ycombinator.com" not in candidate and candidate:
                            website_url = candidate
                            break

                # Founders
                for f_sel in [
                    ".founder-name", "[class*='founder'] h3",
                    "[class*='Founder'] h3", "h3[class*='name']"
                ]:
                    founder_els = await page.query_selector_all(f_sel)
                    if founder_els:
                        names = [clean(await el.inner_text()) for el in founder_els[:2]]
                        founder_name = ", ".join(n for n in names if n)
                        break

                # Batch
                for b_sel in ["[class*='batch']", "[class*='Batch']", "span:has-text('W2'), span:has-text('S2')"]:
                    try:
                        batch_el = await page.query_selector(b_sel)
                        if batch_el:
                            batch = clean(await batch_el.inner_text())
                            break
                    except Exception:
                        pass

                # If description still empty, grab from company page
                if not description:
                    for p_sel in ["[class*='description'] p", "p[class*='tagline']", "meta[name='description']"]:
                        p_el = await page.query_selector(p_sel)
                        if p_el:
                            if p_el.tag_name == "meta" if hasattr(p_el, 'tag_name') else False:
                                description = clean(await p_el.get_attribute("content") or "")
                            else:
                                description = clean(await p_el.inner_text())
                            if description:
                                break

            except Exception as e:
                logger.debug(f"  Enrichment failed for {company_name}: {e}")

            lead = {
                "company_name": company_name,
                "website_url":  website_url or yc_url,
                "founder_name": founder_name,
                "description":  description,
                "source":       "yc",
                "batch":        batch,
                "rank":         infer_rank(description, batch),
                "status":       "new",
            }
            leads.append(lead)
            logger.info(f"  ✓ {company_name} [{batch or 'no batch'}]")

            # Return to list
            await page.goto(YC_LIST_URL, wait_until="domcontentloaded", timeout=30_000)
            await _wait_for_content(page, delay=SCRAPE_DELAY_SECONDS)

        except Exception as e:
            logger.warning(f"  ✗ YC card error: {e}")
            continue

    return leads


# ── Product Hunt Scraper ──────────────────────────────────────────────────────

PH_URL = "https://www.producthunt.com/topics/artificial-intelligence"

async def scrape_producthunt(page: Page, max_leads: int) -> list[dict]:
    logger.info("🔍 PH — navigating to AI category…")
    leads: list[dict] = []

    await page.goto(PH_URL, wait_until="domcontentloaded", timeout=60_000)
    await _wait_for_content(page)
    await _scroll_to_bottom(page, max_scrolls=8)

    # Collect post links
    post_links_raw = await page.query_selector_all('a[href^="/posts/"]')
    seen_hrefs: set[str] = set()
    unique_links: list[str] = []
    for lnk in post_links_raw:
        href = (await lnk.get_attribute("href") or "").strip()
        if href and href not in seen_hrefs and len(href) > 7 and not href.endswith("#"):
            seen_hrefs.add(href)
            unique_links.append(href)

    logger.info(f"  PH: {len(unique_links)} unique post links")

    for href in unique_links[:max_leads]:
        try:
            post_url = f"https://www.producthunt.com{href}"
            await page.goto(post_url, wait_until="domcontentloaded", timeout=30_000)
            await _wait_for_content(page, delay=0.8)

            # Title — try multiple selectors
            title = ""
            for sel in ["h1", "[data-test='product-name'] h1", "h1[class*='title']"]:
                el = await page.query_selector(sel)
                if el:
                    title = clean(await el.inner_text())
                    if title:
                        break

            # Description / tagline
            description = ""
            for sel in ['[data-test="product-tagline"]', ".tagline", 'meta[name="description"]', 'meta[property="og:description"]']:
                el = await page.query_selector(sel)
                if el:
                    tag = await el.get_property("tagName")
                    tag_str = (await tag.json_value() or "").lower()
                    if tag_str == "meta":
                        description = clean(await el.get_attribute("content") or "")
                    else:
                        description = clean(await el.inner_text())
                    if description:
                        break

            # External website
            website_url = post_url
            for sel in [
                'a[data-test="visit-product-button"]',
                'a[rel~="nofollow"][href^="http"]',
                'a[class*="visit"]',
            ]:
                el = await page.query_selector(sel)
                if el:
                    href_val = clean(await el.get_attribute("href") or "")
                    if href_val and "producthunt.com" not in href_val:
                        website_url = href_val
                        break

            # Maker name
            founder_name = ""
            for sel in ['[class*="maker"] a', '[data-test="maker-name"]', 'a[class*="Maker"]']:
                el = await page.query_selector(sel)
                if el:
                    founder_name = clean(await el.inner_text())
                    if founder_name:
                        break

            if not title:
                continue

            lead = {
                "company_name": title,
                "website_url":  website_url,
                "founder_name": founder_name,
                "description":  description,
                "source":       "producthunt",
                "batch":        "",
                "rank":         infer_rank(description),
                "status":       "new",
            }
            leads.append(lead)
            logger.info(f"  ✓ {title}")

        except Exception as e:
            logger.warning(f"  ✗ PH post error: {e}")
            continue

    return leads


# ── Email hunter (best-effort) ────────────────────────────────────────────────

def guess_email(company_name: str, website_url: str) -> str:
    if not website_url:
        return ""
    domain = re.sub(r"^https?://(www\.)?", "", website_url).split("/")[0].lower()
    if not domain or "." not in domain:
        return ""
    return f"founder@{domain}"


# ── Main runner ───────────────────────────────────────────────────────────────

async def run_scraper(source: str = "all", max_leads: int = MAX_LEADS_PER_RUN) -> int:
    total = 0
    async with async_playwright() as pw:
        browser: Browser = await pw.chromium.launch(
            headless=HEADLESS,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            java_script_enabled=True,
        )
        page = await ctx.new_page()

        tasks: list[tuple[str, any]] = []
        if source in ("yc", "all"):
            tasks.append(("yc", lambda: scrape_yc(page, max_leads)))
        if source in ("producthunt", "ph", "all"):
            tasks.append(("producthunt", lambda: scrape_producthunt(page, max_leads)))

        for name, coro_factory in tasks:
            logger.info(f"\n{'='*60}\n  Running {name.upper()} scraper\n{'='*60}")
            try:
                leads = await coro_factory()
                for lead in leads:
                    lead["email"] = guess_email(lead["company_name"], lead["website_url"])
                    try:
                        row = upsert_lead(lead)
                        logger.info(f"  DB ✓ {lead['company_name']} → id={row.get('id','?')[:8]}…")
                        total += 1
                    except Exception as e:
                        logger.error(f"  DB ✗ {lead['company_name']}: {e}")
            except Exception as e:
                logger.error(f"Scraper {name} failed: {e}")

        await browser.close()

    logger.info(f"\n✅  Scraped + saved {total} leads total.")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="War Machine — Lead Scraper")
    parser.add_argument("--source", default="all", choices=["yc", "producthunt", "ph", "all"])
    parser.add_argument("--max",    type=int, default=MAX_LEADS_PER_RUN)
    args = parser.parse_args()
    asyncio.run(run_scraper(source=args.source, max_leads=args.max))
