# War Machine v2.0 — Shadow Fleet

Standalone lead-gen pipeline and Electric Purple intelligence dashboard for ForgeGuard outreach.

## Stack

- **Python** — `pipeline.py`, `scraper.py`, `outreach.py`, `tracker.py` → Supabase `leads` + `war_machine_stats`
- **Next.js 15** — `/dashboard` Shadow Agency UI, `/api/track/[token]` click tracker

## Quick start

```bash
cp .env.example .env
pip install -r requirements.txt
npm install
npm run dev
python pipeline.py --stage report
```

## Deploy

- **Dashboard:** Vercel (`npm run build`)
- **Pipeline:** Railway via `Procfile` or GitHub Actions cron
