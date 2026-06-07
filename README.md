# AI Search Visibility Tracker

Track how a brand appears inside **real** AI interfaces — ChatGPT, Gemini,
Perplexity, Google AI Overviews, and Google AI Mode — measuring visibility,
sentiment/framing, citations, and competitors.

> Runs locally with **zero external services** (SQLite + local disk + in-process
> tasks), and scales up to **Postgres + Celery/Redis + Cloudflare R2** purely by
> setting env vars. Each piece is pluggable with a graceful fallback.

## Architecture

```
                      ┌─────────────── Celery worker(s) ───────────────┐
   FastAPI API  ──►   │  Playwright/SerpAPI capture → storage → NER →   │  ──►  Postgres
   (enqueue job)      │  ranking → local sentiment → LLM competitors   │       (or SQLite)
        ▲             └────────────────────────────────────────────────┘            │
        │                              artifacts ▼                                   │
   React dashboard  ◄────── Analytics API ◄──── Cloudflare R2 (or local ./storage) ◄┘
```

When no broker is configured the capture runs as an in-process background task
instead of on a worker — same code path, no Redis needed for local dev.

Layers (all decoupled):

- `backend/providers/*` — capture adapters: Playwright (chatgpt/gemini/perplexity) + SerpAPI (google_ai/google_ai_mode).
- `backend/capture/` — orchestrator (rate limit, backoff, circuit breaker, cache) + LLM competitor detection.
- `backend/tasks/` — Celery app + dispatcher (falls back to FastAPI BackgroundTasks).
- `backend/storage/` — pluggable artifact backend: local disk **or** Cloudflare R2 (S3).
- `backend/processing/` — spaCy NER + rapidfuzz normalization + local HF sentiment.
- `backend/ranking/` — visibility / position / citation scoring.
- `backend/llm/` — Gemini client (key rotation) for prompt suggestions + competitor detection.
- `backend/analytics/` + `backend/api/` — read views + FastAPI routes.

## Scaling up (all optional, env-driven)

| Capability        | Env to set                                              | Fallback when unset            |
| ----------------- | ------------------------------------------------------- | ------------------------------ |
| **Postgres**      | `DATABASE_URL=postgresql+psycopg://…`                   | SQLite (`sqlite:///…`)         |
| **Celery/Redis**  | `CELERY_BROKER_URL=redis://…`                           | in-process BackgroundTasks     |
| **Cloudflare R2** | `R2_ACCOUNT_ID/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY/R2_BUCKET` | local `./storage`     |
| **Key rotation**  | `SERP_API_KEYS=a,b,c` · `GEMINI_API_KEYS=a,b,c`         | single `SERP_API_KEY`/`GEMINI_API_KEY` |

Start a worker (when using Celery):

```bash
celery -A backend.tasks.celery_app worker --loglevel=info
```

**Notes on the managed services:**
- *Postgres (Supabase pooler)*: use the pooled endpoint (`…pooler.supabase.com:6543`).
  The engine disables psycopg3 prepared statements (required for pgbouncer
  transaction mode) and enables `pool_pre_ping`. Schema is created automatically;
  a dialect-aware in-place column migration runs at startup (use Alembic for
  anything heavier).
- *R2*: artifacts are written under `raw/ processed/ screenshots/ html/` keys and
  served via presigned URLs (or `R2_PUBLIC_BASE_URL` if you front it with a CDN).
- *Key rotation*: round-robins keys and advances to the next on quota/`429`/`401`.

### Run with the task queue live (local)

```bash
# 1. Redis broker (macOS) — persists across reboots
brew install redis
brew services start redis        # redis-cli ping → PONG

# 2. point the app at it (.env)
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# 3. run the API and a worker in separate terminals
uvicorn backend.main:app --reload
./scripts/worker.sh              # celery -A backend.tasks.celery_app worker --pool=solo
```

With the broker set, `POST /capture` returns immediately (`"mode": "celery"`) and
the worker performs the scrape + NLP. Unset `CELERY_BROKER_URL` to revert to the
in-process fallback. The worker uses the `solo` pool to avoid macOS fork-safety
crashes from torch/Playwright.

## Folder layout

```
ai_tracker/
├── backend/
│   ├── api/                # FastAPI routes + schemas
│   ├── providers/          # chatgpt/ gemini/ google_ai/ + base.py
│   ├── capture/            # orchestrator
│   ├── processing/         # NER + normalizer + pipeline
│   ├── ranking/            # visibility scoring
│   ├── analytics/          # dashboard data
│   ├── models/             # SQLAlchemy models
│   ├── storage/            # raw/processed JSON store
│   ├── database/           # SQLAlchemy session
│   ├── utils/              # helpers
│   ├── config.py
│   └── main.py             # FastAPI entrypoint
├── frontend/               # Vite + React + Tailwind + Recharts
├── storage/
│   ├── raw/                # /storage/raw/{run_id}.json
│   ├── processed/          # /storage/processed/{run_id}.json
│   ├── screenshots/
│   └── html/
├── scripts/                # init_db.py, login_provider.py, seed_example.py
├── requirements.txt
├── .env.example
└── README.md
```

## Setup

### 1. Backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Install the browser. patchright ships a Chrome build patched for CDP-stealth
# (required to pass Cloudflare on ChatGPT and Google). If you also have Google
# Chrome installed on your system, it'll be used preferentially via channel="chrome".
patchright install chrome
python -m playwright install chromium   # fallback only

python -m spacy download en_core_web_sm

cp .env.example .env

# create SQLite tables
python -m scripts.init_db
```

### 2. Provider auth status

All providers run **anonymously** — no login required.

| Provider         | Type    | Notes                                                                              |
| ---------------- | ------- | ---------------------------------------------------------------------------------- |
| `chatgpt`        | Browser | Anonymous `chatgpt.com`. Cloudflare Turnstile handled by patchright + stealth.     |
| `gemini`         | Browser | `gemini.google.com` allows signed-out queries; consent auto-dismissed.             |
| `perplexity`     | Browser | Anonymous `perplexity.ai`; citation-rich. Cloudflare handled by patchright.        |
| `google_ai`      | SerpAPI | Google AI Overview via SerpAPI (two-step `page_token`). Needs `SERP_API_KEY`.      |
| `google_ai_mode` | SerpAPI | Google AI Mode via SerpAPI (`engine=google_ai_mode`). Needs `SERP_API_KEY`.        |

Browser providers honor an optional `PROXY_URL` for proxy rotation. SerpAPI
providers need no browser and never hit Cloudflare.

Optional: if you *want* to use a signed-in session (higher ChatGPT rate limits,
or Gemini features only available to logged-in users), run:

```bash
python -m scripts.login_provider chatgpt
python -m scripts.login_provider gemini
```

Cookies persist to `./.browser_profiles/<provider>/` and are reused automatically.

#### Cloudflare / consent on capture

ChatGPT and Google Search sit behind Cloudflare Turnstile, which detects
Playwright at the **CDP (Chrome DevTools Protocol)** level — no JS-level
stealth script can hide this. We address it with:

- **patchright** — a drop-in replacement for `playwright` that patches CDP
  fingerprints. This is the actual fix; the JS stealth and launch args alone
  are not enough. Falls back to vanilla playwright if patchright isn't installed
  (you'll likely get challenged in that case).
- **Real Chrome** (`channel="chrome"`) when installed, otherwise patchright's
  bundled Chrome build, otherwise bundled Chromium.
- **Persistent profile** so clearance cookies survive between runs.
- **`wait_for_cloudflare`** that pauses while the challenge is visible.
- **JS-level stealth** as a belt-and-suspenders defense in depth.

**`HEADLESS=false` clears challenges far more reliably than headless mode.**
Install Google Chrome (not just Chromium) for best results.

### 3. (Optional) Seed example data so you can poke the dashboard without running a capture

```bash
python -m scripts.seed_example
```

### 4. Start backend

```bash
uvicorn backend.main:app --reload
# → http://127.0.0.1:8000
```

### 5. Start frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

## Usage

1. Open the dashboard at `http://localhost:5173`.
2. Create a project: name, domain, up to 5 prompts, optional competitors.
3. Click **Run capture**. The backend launches Playwright in the background,
   visits each provider, submits each prompt, waits for streaming completion,
   captures the rendered DOM + a full-page screenshot, and writes a raw JSON
   artifact under `storage/raw/`.
4. The processing layer runs immediately after each capture: spaCy NER →
   rapidfuzz normalization → mentions + citations persisted to SQLite.
5. The Overview / Runs / Competitors / Providers pages query the analytics API
   and render charts (Recharts) + tables.

## What gets stored per run

```json
{
  "provider": "chatgpt",
  "prompt": "best project management software",
  "timestamp": "2026-05-25T18:00:00Z",
  "response_text": "...",
  "citations": [{ "title": "Notion", "url": "https://notion.so", "domain": "notion.so" }],
  "links": [...],
  "metadata": { "response_time": 12.3, "has_citations": true },
  "screenshot_path": "storage/screenshots/<run_id>.png",
  "html_path": "storage/html/<run_id>.html",
  "has_ai_overview": true
}
```

Raw data is immutable. Re-running the processing layer (`POST /api/projects/{id}/reprocess`
or the **Reprocess** button) re-derives mentions, citations, and rankings without
re-scraping.

## Dashboard pages

- **Overview** — visibility score, mention/citation totals, top-brands bar chart,
  per-provider pie, a live **Capture Pipeline** panel, and a **Visibility Trend**
  line chart (Competitor AI Visibility vs. your AI Agent Mentions over time).
- **Prompt Runs** — every (provider × prompt) run with status + detail modal.
- **Competitors** — co-mention analysis vs. the target brand.
- **Providers** — brand × provider mention matrix.
- **History** — chronological log of competitors added (manual vs. auto-detected)
  and queries added.

### Live capture pipeline

Clicking **Run capture** pre-creates one `pending` run per (provider × prompt)
and runs them in the background. The Overview page's **Capture Pipeline** panel
polls every 2s and shows each step move through `Queued → Running →
Succeeded/Failed`, grouped by provider — a Profound-style orchestrator view that
stops polling once all steps settle.

## Brand intelligence

### Sentiment & framing (local model)

Runs entirely **locally** in the processing layer — no API cost, no per-run
network latency. For each run we detect how the target brand is portrayed:

- **sentiment**: positive / neutral / negative
- **framing**: leader / also-ran / cautionary / not-mentioned

Sentiment uses a HuggingFace model (`cardiffnlp/twitter-roberta-base-sentiment-latest`
by default, `SENTIMENT_MODEL`), loaded lazily on first use. If `transformers`/
`torch` aren't installed it falls back to a built-in lexicon, so it always
works. Framing is a rule-based read over the brand's sentences combined with the
sentiment label. Shown per-run (Runs table + detail) and summarised on the
Overview. Toggle with `ENABLE_SENTIMENT`. This is what turns a mention *counter*
into a brand-intelligence tool.

### LLM features (Gemini)

With `GEMINI_API_KEY` set, two occasional (not per-run) features turn on:

- **Prompt suggestions** — *Overview → Prompt suggestions → Generate.* Gemini
  infers your industry from the domain + tracked prompts and proposes
  high-intent queries your brand *should* appear in (unaided — brand name
  excluded). Select and append them in one click.
- **Competitor auto-detection** — replaces the old noisy per-run NER inference.
  Gemini receives the domain + prompts + raw AI responses and returns clean,
  deduplicated competitor brands (with a one-line reason each). Runs
  automatically at the end of a capture batch, and on demand via
  *Competitors → Auto-detect (AI)*.

Both degrade gracefully: if `GEMINI_API_KEY` is unset they simply no-op and the
core capture/processing pipeline is unaffected.

## Geo-location

Each project can carry a default `geo_location` (e.g. `"United States"`,
`"London, England"`, `"Mumbai, India"`). It's passed to SerpAPI's `location`
param for location-aware AI Overview / AI Mode results. Precedence at capture
time: **request override → project default → `DEFAULT_GEO_LOCATION`**.

## Caching, TTL & resilience

These are configured in `.env` (sensible defaults shown):

| Concern            | Setting(s)                                                              | Behaviour                                                                                                  |
| ------------------ | ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| **Result cache**   | `CACHE_TTL_HOURS=24`                                                     | A re-run reuses a recent successful capture for the same (project, provider, prompt, geo). `force_refresh` (capture menu) bypasses it. Cached runs are flagged in the UI. |
| **Artifact TTL**   | `ARTIFACT_TTL_DAYS=7`, `CLEANUP_INTERVAL_HOURS=24`                       | Raw JSON + screenshots + HTML older than the TTL are purged (runs marked `purged`); aggregated DB rows are kept. Runs once at startup, then on the interval. Manual: `python -m scripts.cleanup [days]`. |
| **Rate limiting**  | `PROVIDER_MIN_DELAY_SECONDS=3`                                          | Minimum delay between requests to the same provider.                                                       |
| **Backoff**        | `PROVIDER_MAX_RETRIES=2`, `PROVIDER_BACKOFF_BASE=2.0`                    | Failed captures retry with exponential backoff (`base**attempt` seconds).                                  |
| **Circuit breaker**| `CIRCUIT_BREAKER_THRESHOLD=3`                                            | After N consecutive failures for a provider, remaining jobs in that batch fail fast instead of hammering.  |
| **Proxy (hook)**   | `PROXY_URL`                                                             | Optional proxy server for browser providers — proxy-rotation integration point.                            |

## Visibility score

```
visibility_score =
   (prompts_where_brand_appears / total_prompts) * 100
   + first_mention_bonus            (up to 10)
   + min(citations, 5) * 2          (up to 10)
   + multi_provider_bonus           ((providers_seen - 1) * 5)
   → capped at 100
```

## Notes on selectors

ChatGPT and Gemini ship UI changes regularly. Each provider keeps multiple
fallback selectors. When a capture fails, the run row in the dashboard shows the
error, and the screenshot + HTML are saved so you can replay processing later
without re-scraping. To re-run all processing after updating selectors or NER:

```bash
curl -X POST http://127.0.0.1:8000/api/projects/<id>/reprocess
```

## Tech stack

- **Backend**: Python, FastAPI, Playwright (async), SQLAlchemy 2, SQLite, spaCy, rapidfuzz.
- **Frontend**: React 18, Vite, TailwindCSS, Recharts, shadcn-styled components.
