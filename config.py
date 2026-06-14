"""
config.py — War Machine Configuration
──────────────────────────────────────────────────────────────────────────────
Central config hub. All secrets come from environment variables.
Never hard-code keys here — use .env + python-dotenv locally,
or GitHub Actions / Railway secrets in production.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── Supabase ────────────────────────────────────────────────────────────────
SUPABASE_URL           = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY   = os.environ["SUPABASE_SERVICE_ROLE_KEY"]   # service role — bypasses RLS

# ─── OpenRouter ──────────────────────────────────────────────────────────────
OPENROUTER_API_KEY     = os.getenv("OPENROUTER_API_KEY", "")

# ─── Resend ───────────────────────────────────────────────────────────────────
RESEND_API_KEY         = os.getenv("RESEND_API_KEY", "")

# ─── ForgeGuard handshake (POST /scrape) ─────────────────────────────────────
INTERNAL_SCAN_TOKEN    = os.getenv("INTERNAL_SCAN_TOKEN", "")
OPENROUTER_MODEL       = os.getenv("OPENROUTER_MODEL", "")  # empty = use tiered routing

FROM_EMAIL             = os.getenv("FROM_EMAIL", "recon@forgeguard.ai")
FROM_NAME              = os.getenv("FROM_NAME", "ForgeGuard AI — Recon Division")

# ─── App ──────────────────────────────────────────────────────────────────────
APP_BASE_URL           = os.getenv("APP_BASE_URL", "https://forgeguard.ai")
TRACK_BASE_URL         = os.getenv(
    "TRACK_BASE_URL",
    f"{os.getenv('NEXT_PUBLIC_APP_URL', 'http://localhost:3000')}/api/track",
)

# ─── Scraper ──────────────────────────────────────────────────────────────────
# Max leads to scrape per run (keep low for dev, crank up in prod)
MAX_LEADS_PER_RUN      = int(os.getenv("MAX_LEADS_PER_RUN", "50"))
HEADLESS               = os.getenv("HEADLESS", "true").lower() == "true"

# ─── Rate limiting ────────────────────────────────────────────────────────────
EMAIL_DELAY_SECONDS    = float(os.getenv("EMAIL_DELAY_SECONDS", "2.5"))   # between sends
SCRAPE_DELAY_SECONDS   = float(os.getenv("SCRAPE_DELAY_SECONDS", "1.5"))  # between page loads

# ─── Marineford rank thresholds ──────────────────────────────────────────────
# Ranks based on funding / team size (scraped from YC/PH)
RANK_ADMIRAL    = "Admiral"     # Series A+ or 20+ employees
RANK_LIEUTENANT = "Lieutenant"  # Seed / 5-20 employees
RANK_RECRUIT    = "Recruit"     # Pre-seed / < 5 employees / unknown
