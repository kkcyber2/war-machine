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

## Send gate — read this before running outreach

Every outbound email passes through `outreach_policy.evaluate_send()`. It is a
pure function: the clock, the suppression list and the counters are passed in,
so the rules are unit-tested and no caller can skip them. **A refusal is the
default** — each check is a positive finding that the send is safe.

What it refuses, and why:

| Refusal | Meaning |
|---|---|
| `synthesised_address` | The address was invented (`founder@<domain>`), not published by its owner. Never sendable, under any flag. |
| `unknown_provenance` | `contact_source` is empty or unrecognised. Only `site_mailto`, `site_text`, `platform_contact` and `manual` are sendable. |
| `automated_desk` | `abuse@`, `postmaster@`, `no-reply@`, … — a complaint, not a conversation. |
| `suppressed_email` / `suppressed_domain` | Opted out, bounced, or replied. Absolute. |
| `domain_cooldown` | Same company already contacted inside `DOMAIN_COOLDOWN_DAYS`. |
| `daily_cap_reached` | `DAILY_SEND_CAP` hit for the day. |
| `outside_send_window` | Outside business hours / weekend, per `SEND_WINDOW_*`. |
| `no_postal_address` / `no_unsubscribe` | Legal identification or opt-out missing. |

Two consequences worth knowing:

- **`POSTAL_ADDRESS` and `UNSUBSCRIBE_BASE_URL` are required.** Without them
  every send is refused. That is deliberate: commercial email needs a real
  physical address and a working one-click opt-out.
- **A lead with no published address is stored with `email = ''`** and skipped.
  The scraper no longer invents one. Expect fewer leads than v1 — the
  difference is the fabricated ones.

The runner also refuses to start at all if the suppression list cannot be
loaded, because sending without knowing who opted out cannot be undone.

### Copy honesty guard

`assert_honest_copy()` runs on the rendered HTML and plain text before every
send. It rejects copy that asserts a finding the pipeline never produced
("our recon systems flagged you", "VULNERABILITY DETECTED", "before we publish
the findings"). Negated forms are allowed, so the disclaimer that makes the
email truthful — *"we have not tested your systems, and I'm not claiming we
found anything"* — passes. A template edit that reintroduces a fabricated
finding fails the run instead of reaching an inbox.

## Supabase

Migrations in `supabase/migrations/` (`leads`, `war_machine_stats`). Live ForgeGuard project `nlginrukltrwpkyujzzx` includes these via `LAUNCH_ALL.sql`.

`leads.contact_source` records where each address came from and is required for
the send gate to allow a send. Rows written before that column existed have an
empty value and are refused — backfill them only with an address you can point
at a published source for.

## Troubleshooting 0 leads

If `POST /scrape` returns **202** but `public.leads` stays empty:

1. **Run locally (no DB write):**
   ```bash
   SUPABASE_URL=https://example.supabase.co SUPABASE_SERVICE_ROLE_KEY=dummy \
     python scraper.py --source producthunt --max 5 --dry-run
   ```
   Expect `PH: post_links=N titles=N` with real product names (e.g. Figma, Vercel).

2. **If `post_links=0`**, the scraper saves `debug-ph-list.png` in the working directory and logs `page.title()` plus the first 500 chars of body text — usually a consent wall or bot block.

3. **Product Hunt URL drift:** PH now uses `/products/{slug}` (not `/posts/`). The scraper tries topic → daily leaderboard → homepage, with selector fallbacks.

4. **YC smoke fallback:**
   ```bash
   python scraper.py --source yc --max 3 --dry-run
   ```

5. **Production E2E:** `node scripts/test-scrape.cjs` → wait 90–120s → `SELECT count(*) FROM leads WHERE source='producthunt'`.

## Licence

MIT — see `LICENSE`. Author: Konain Sultan Khan (KK),
https://github.com/kkcyber2
