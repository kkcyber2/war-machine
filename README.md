# War Machine v2 — Shadow Fleet

Standalone lead-gen API + Electric Purple intelligence dashboard for ForgeGuard outreach.

## Two-deploy model

| Component | Host | Purpose |
|-----------|------|---------|
| **API (scraper)** | **Railway** | FastAPI `api_server.py` — `GET /health`, `POST /scrape` (ForgeGuard admin dispatch) |
| **Dashboard** | **Vercel** (optional) | Next.js `/dashboard` Shadow Agency UI + `/api/track/[token]` |

ForgeGuard production (`forgeguard-ai` on Vercel) calls the **Railway API URL**, not the Vercel dashboard:

```env
# forgeguard-ai Vercel production
WAR_MACHINE_URL=https://<war-machine-service>.up.railway.app
INTERNAL_SCAN_TOKEN=<same-byte-match-as-railway>
```

`POST /api/admin/war-machine` on ForgeGuard forwards to Railway `POST /scrape` with `{ "hours": 24, "source": "producthunt_ai" }`.

## Stack

- **Python** — `api_server.py`, `pipeline.py`, `scraper.py`, `outreach.py` → Supabase `leads` + `war_machine_stats`
- **Next.js 15** — `/dashboard` (deploy separately to Vercel project `war-machine`)

## Local API

```bash
cp .env.example .env
pip install -r requirements.txt
playwright install chromium --with-deps
uvicorn api_server:app --reload --port 7871
curl http://localhost:7871/health
```

## Local dashboard

```bash
npm install
npm run dev
```

## Railway deploy

1. Create service from this repo (root is flat — no `war-machine/` subfolder).
2. Set env vars (see `.env.example` + `INTERNAL_SCAN_TOKEN`).
3. `Procfile` / `railway.toml` / `nixpacks.toml` install Playwright Chromium and start uvicorn.
4. Copy public Railway URL into ForgeGuard `WAR_MACHINE_URL`.

## GitHub Actions cron

`.github/workflows/cron.yml` and `war-machine.yml` run `pipeline.py` on schedule (flat repo paths).

## API contract (ForgeGuard compatible)

### `GET /health`
Returns `{ "ok": true, "service": "war-machine", "status": "healthy" }`.

### `POST /scrape`
Auth: `x-internal-scan-token: <INTERNAL_SCAN_TOKEN>` or `Authorization: Bearer <token>`.

Body:
```json
{ "hours": 24, "source": "producthunt_ai" }
```

- **202** — scrape accepted (background Playwright job)
- Maps `producthunt_ai` → Product Hunt scraper

## Supabase

Migrations in `supabase/migrations/` (`leads`, `war_machine_stats`). Live ForgeGuard project `nlginrukltrwpkyujzzx` includes these via `LAUNCH_ALL.sql`.
