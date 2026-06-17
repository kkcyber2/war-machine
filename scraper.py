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
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PWTimeout
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


async def _dismiss_consent(page: Page) -> None:
    """Dismiss cookie/consent banners when present."""
    for sel in [
        'button:has-text("Accept")',
        'button:has-text("Got it")',
        'button:has-text("Allow all")',
        'button:has-text("I agree")',
        '[data-test*="cookie"] button',
        'button[class*="cookie"]',
    ]:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click(timeout=3_000)
                await asyncio.sleep(0.5)
                logger.info("  PH: dismissed consent via %r", sel)
                return
        except Exception:
            continue


def _is_ph_product_href(href: str) -> bool:
    """True when href looks like a Product Hunt product/post detail page."""
    if not href or href.startswith("#"):
        return False
    path = href.split("?")[0].split("#")[0]
    if not path.startswith("/"):
        return False
    blocked = (
        "/topics/", "/collections/", "/login", "/search", "/makers/",
        "/newsletters/", "/changes/", "/about", "/legal", "/sponsor",
        "/stories/", "/shoutouts/", "/discussions/", "/launch/",
    )
    if any(b in path for b in blocked):
        return False
    if "/posts/" in path or "/products/" in path:
        return True
    # Single-segment slug: /my-product
    return bool(re.match(r"^/[a-zA-Z0-9][a-zA-Z0-9_-]*$", path))


def _normalize_ph_href(href: str) -> str:
    path = (href or "").strip().split("?")[0].split("#")[0]
    if not path.startswith("/"):
        return ""
    return path.rstrip("/") or path


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

PH_BASE = "https://www.producthunt.com"
PH_URL = f"{PH_BASE}/topics/artificial-intelligence"

PH_LINK_SELECTORS = [
    'a[href^="/posts/"]',
    'a[href*="/posts/"]',
    'a[href^="/products/"]',
    'a[href*="/products/"]',
    'a[data-test*="post"]',
    'article a[href^="/"]',
]

PH_TITLE_SELECTORS = [
    "h1",
    "[data-test*='name']",
    "[data-test*='product'] h1",
    "[data-test='product-name'] h1",
    "h1[class*='title']",
    'meta[property="og:title"]',
    'meta[name="twitter:title"]',
]

PH_TAGLINE_SELECTORS = [
    '[data-test*="tagline"]',
    '[data-test*="description"]',
    '[data-test="product-tagline"]',
    ".tagline",
    'meta[property="og:description"]',
    'meta[name="description"]',
]

PH_WEBSITE_SELECTORS = [
    'a[data-test*="visit"]',
    'a[data-test="visit-product-button"]',
    'a[rel~="nofollow"][href^="http"]',
    'a[class*="visit"]',
    'a[href^="http"]:not([href*="producthunt"])',
]


def _ph_list_urls() -> list[str]:
    today = datetime.now(timezone.utc)
    return [
        PH_URL,
        f"{PH_BASE}/leaderboard/daily/{today.year}/{today.month}/{today.day}",
        PH_BASE + "/",
    ]


PH_SKIP_TEXT = frozenset({
    "view all", "see all", "more", "reviews", "review",
})
PH_META_FRAGMENTS = (
    "launched this month", "launched today", "launched yesterday",
    "launched this week", "promoted", "sponsor",
)


def _parse_ph_link_text(text: str) -> tuple[str, str]:
    """Parse product name + tagline from PH list anchor innerText."""
    raw = clean(text.replace("\n", " | "))
    if not raw:
        return "", ""
    parts = [p.strip() for p in raw.split("|") if p.strip()]
    if not parts:
        return "", ""
    title = parts[0]
    if title.lower() in PH_SKIP_TEXT or "review" in title.lower():
        return "", ""
    tagline_parts = [
        p for p in parts[1:]
        if p.lower() not in PH_SKIP_TEXT
        and not any(m in p.lower() for m in PH_META_FRAGMENTS)
        and not re.search(r"\d+\s*reviews?", p, re.I)
    ]
    description = tagline_parts[-1] if tagline_parts else ""
    return title, description


def _product_slug_href(href: str) -> str:
    """Normalize to /products/{slug} — drops /reviews and query strings."""
    path = _normalize_ph_href(href)
    m = re.match(r"^/products/([a-zA-Z0-9_-]+)", path)
    if not m:
        return ""
    return f"/products/{m.group(1)}"


async def _is_cloudflare_challenge(page: Page) -> bool:
    title = (await page.title() or "").lower()
    if "just a moment" in title or title.strip() == "www.producthunt.com":
        return True
    try:
        body = (await page.evaluate("() => document.body?.innerText || ''") or "").lower()
        if "checking your browser" in body or "cloudflare" in body[:400]:
            return True
    except Exception:
        pass
    return False


async def _collect_ph_links(page: Page) -> tuple[list[dict], str]:
    """Collect product cards from the current list page."""
    seen_slugs: set[str] = set()
    items: list[dict] = []
    matched = "none"

    for sel in PH_LINK_SELECTORS:
        nodes = await page.query_selector_all(sel)
        if not nodes:
            continue
        batch: list[dict] = []
        for node in nodes:
            href = _product_slug_href(await node.get_attribute("href") or "")
            if not href or href in seen_slugs:
                continue
            text = await node.inner_text()
            title, description = _parse_ph_link_text(text)
            if not title:
                img = await node.query_selector("img[alt]")
                if img:
                    title = clean(await img.get_attribute("alt") or "")
            if not title or title.lower() in PH_SKIP_TEXT:
                continue
            seen_slugs.add(href)
            batch.append({
                "href": href,
                "title": title,
                "description": description,
            })
        if batch:
            matched = sel
            items.extend(batch)

    return items, matched


async def _extract_text_or_meta(page_or_el, sel: str) -> str:
    el = await page_or_el.query_selector(sel)
    if not el:
        return ""
    tag = (await el.evaluate("el => el.tagName") or "").lower()
    if tag == "meta":
        return clean(await el.get_attribute("content") or "")
    return clean(await el.inner_text())


async def _extract_ph_card_fields(link_el) -> dict[str, str]:
    """Try title/tagline from list card without visiting detail page."""
    title = ""
    description = ""
    try:
        card = await link_el.evaluate_handle(
            "el => el.closest('article, li, [data-test], section, div[class*=\"item\"]') || el.parentElement"
        )
        card_el = card.as_element()
        if card_el:
            for sel in ["h2", "h3", "[data-test*='name']", "strong"]:
                title = await _extract_text_or_meta(card_el, sel)
                if title:
                    break
            for sel in PH_TAGLINE_SELECTORS[:4]:
                description = await _extract_text_or_meta(card_el, sel)
                if description:
                    break
    except Exception:
        pass
    return {"title": title, "description": description}


async def _extract_ph_detail(page: Page, post_url: str, card_hint: dict[str, str]) -> Optional[dict]:
    title = card_hint.get("title", "")
    description = card_hint.get("description", "")

    if not title:
        for sel in PH_TITLE_SELECTORS:
            title = await _extract_text_or_meta(page, sel)
            if title:
                break
        # og:title often includes " | Product Hunt"
        if title.endswith("| Product Hunt"):
            title = clean(title.rsplit("|", 1)[0])

    if not description:
        for sel in PH_TAGLINE_SELECTORS:
            description = await _extract_text_or_meta(page, sel)
            if description:
                break

    website_url = post_url
    for sel in PH_WEBSITE_SELECTORS:
        el = await page.query_selector(sel)
        if el:
            href_val = clean(await el.get_attribute("href") or "")
            if href_val and "producthunt.com" not in href_val.lower():
                website_url = href_val
                break

    founder_name = ""
    for sel in ['[class*="maker"] a', '[data-test="maker-name"]', 'a[class*="Maker"]']:
        el = await page.query_selector(sel)
        if el:
            founder_name = clean(await el.inner_text())
            if founder_name:
                break

    if not title:
        return None

    return {
        "company_name": title,
        "website_url": website_url,
        "founder_name": founder_name,
        "description": description,
        "source": "producthunt",
        "batch": "",
        "rank": infer_rank(description),
        "status": "new",
    }


async def scrape_producthunt(page: Page, max_leads: int) -> list[dict]:
    logger.info("🔍 PH — navigating to AI category…")
    leads: list[dict] = []
    list_items: list[dict] = []
    matched_selector = "none"

    for list_url in _ph_list_urls():
        logger.info("  PH: trying list URL %s", list_url)
        await page.goto(list_url, wait_until="domcontentloaded", timeout=60_000)
        await _dismiss_consent(page)

        loaded = False
        for sel in PH_LINK_SELECTORS:
            try:
                await page.wait_for_selector(sel, timeout=15_000)
                loaded = True
                break
            except PWTimeout:
                continue
        if not loaded:
            logger.warning("  PH: no link selector matched within 15s on %s", list_url)

        await _wait_for_content(page)
        await _scroll_to_bottom(page, max_scrolls=8)

        items, sel = await _collect_ph_links(page)
        if items:
            list_items = items
            matched_selector = sel
            logger.info("  PH: selector %r → %d products on %s", sel, len(items), list_url)
            break

    post_links_count = len(list_items)

    if not list_items:
        try:
            await page.screenshot(path="debug-ph-list.png", full_page=True)
        except Exception as e:
            logger.warning("  PH: screenshot failed: %s", e)
        page_title = await page.title()
        body_snip = await page.evaluate("() => (document.body?.innerText || '').slice(0, 500)")
        logger.warning(
            "PH blocked — 0 posts (title=%r, body=%r, selector=%s)",
            page_title,
            body_snip,
            matched_selector,
        )
        logger.info("PH: post_links=%d titles=%d upserted=%d", 0, 0, 0)
        return leads

    for item in list_items[:max_leads]:
        href = item["href"]
        try:
            post_url = urljoin(PH_BASE, href)
            title = item["title"]
            description = item.get("description", "")
            website_url = post_url
            founder_name = ""

            # Detail page only when list card lacks a title (spec: avoid per-post nav when possible)
            if not title:
                try:
                    await page.goto(post_url, wait_until="domcontentloaded", timeout=30_000)
                    await _dismiss_consent(page)
                    await _wait_for_content(page, delay=0.6)
                    if await _is_cloudflare_challenge(page):
                        logger.warning("  PH: Cloudflare on %s — skipping", href)
                        continue
                    detail = await _extract_ph_detail(page, post_url, {"title": "", "description": description})
                    if not detail:
                        continue
                    title = detail["company_name"]
                    description = detail["description"] or description
                    if detail["website_url"] and "producthunt.com" not in detail["website_url"].lower():
                        website_url = detail["website_url"]
                    founder_name = detail.get("founder_name", "")
                except Exception as e:
                    logger.debug("  PH detail failed %s: %s", href, e)
                    continue

            if not title or title.lower() in {"www.producthunt.com", "just a moment"}:
                continue
            if "cloudflare.com" in website_url.lower():
                website_url = post_url

            lead = {
                "company_name": title,
                "website_url": website_url,
                "founder_name": founder_name,
                "description": description,
                "source": "producthunt",
                "batch": "",
                "rank": infer_rank(description),
                "status": "new",
            }
            leads.append(lead)
            logger.info("  ✓ %s", title)

        except Exception as e:
            logger.warning("  ✗ PH post error (%s): %s", href, e)
            continue

    logger.info(
        "PH: post_links=%d titles=%d upserted=%d (selector=%s)",
        post_links_count,
        len(leads),
        len(leads),
        matched_selector,
    )
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

async def run_scraper(source: str = "all", max_leads: int = MAX_LEADS_PER_RUN, dry_run: bool = False) -> int:
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
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
            },
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
                    if dry_run:
                        logger.info("  DRY ✓ %s — %s", lead["company_name"], lead.get("website_url", ""))
                        total += 1
                        continue
                    from db import upsert_lead
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
    parser.add_argument("--dry-run", action="store_true", help="Scrape only — skip Supabase upsert")
    args = parser.parse_args()
    asyncio.run(run_scraper(source=args.source, max_leads=args.max, dry_run=args.dry_run))
