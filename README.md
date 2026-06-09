# AI Search Visibility Tracker

Track how a brand appears inside **real** AI interfaces — ChatGPT, Gemini,
Perplexity, Google AI Overviews, and Google AI Mode — measuring visibility,
sentiment/framing, citations, and competitors.

> Runs locally with **zero external services** (SQLite + local disk + in-process
> tasks), and scales up to **Postgres + Celery/Redis + Supabase Storage** purely
> by setting env vars. Each piece is pluggable with a graceful fallback.

---

## Architecture

```text
                      ┌─────────────── Celery worker(s) ───────────────┐
   FastAPI API  ──►   │  Playwright/SerpAPI capture → storage → NER →   │  ──►  Postgres
   (enqueue job)      │  ranking → local sentiment → LLM competitors   │       (or SQLite)
        ▲             └────────────────────────────────────────────────┘            │
        │                              artifacts ▼                                   │
   React dashboard  ◄────── Analytics API ◄──── Supabase Storage (or local ./storage) ◄┘
```

When no broker is configured the capture runs as an in-process background task
instead of on a worker — same code path, no Redis needed for local dev.

Layers (all decoupled):

- `backend/providers/*` — capture adapters: Playwright (chatgpt/gemini/perplexity) + SerpAPI (google_ai/google_ai_mode).
- `backend/capture/` — orchestrator (rate limit, backoff, circuit breaker, cache) + LLM competitor detection.
- `backend/tasks/` — Celery app + dispatcher: fans capture out one task per provider (parallel across workers) → chord callback runs NLP sequentially. Falls back to FastAPI BackgroundTasks with the same capture-parallel / process-sequential split.
- `backend/storage/` — pluggable artifact backend: local disk **or** Supabase Storage (S3).
- `backend/processing/` — spaCy NER + rapidfuzz normalization + local HF sentiment.
- `backend/ranking/` — visibility / position / citation scoring.
- `backend/llm/` — Gemini client (key rotation) for prompt suggestions + competitor detection.
- `backend/analytics/` + `backend/api/` — read views + FastAPI routes.

---

## Folder Layout

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

---

## Project Setup

This walks through the **scaled stack** as the default path — Postgres + Celery/Redis +
Supabase Storage — wired purely through `.env`. If you'd rather run with zero external
services, see the **Local fallback** subpoint at the end of the backend section; the same
code paths degrade gracefully to SQLite + local disk + in-process tasks.

### How to Run the Project

#### Backend

##### 1. Install dependencies

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Install the browser. patchright ships a Chrome build patched for CDP-stealth
# (required to pass Cloudflare on ChatGPT and Google). If you also have Google
# Chrome installed on your system, it'll be used preferentially via channel="chrome".
patchright install chrome
python -m playwright install chromium   # fallback only

# Download language model
python -m spacy download en_core_web_sm

# Configure environment
cp .env.example .env
```

##### 2. Configure the scaled infrastructure (`.env`)

Set these in `.env` to run against managed Postgres, a Celery/Redis task queue, and
Supabase Storage:

| Capability            | Env var(s)                                                                                                                          | Notes                                                                                   |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| **Postgres**          | `DATABASE_URL=postgresql+psycopg://…`                                                                                             | Use the Supabase pooled endpoint (`…pooler.supabase.com:6543`). Schema auto-migrates at boot. |
| **Celery / Redis**    | `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`                                                                                       | Offloads browser scrapes + NLP to worker processes (survive API restarts).              |
| **Supabase Storage**  | `SUPABASE_PROJECT_REF`, `SUPABASE_S3_REGION`, `SUPABASE_S3_ACCESS_KEY_ID`, `SUPABASE_S3_SECRET_ACCESS_KEY`, `SUPABASE_STORAGE_BUCKET` | Raw JSON, screenshots, and HTML stream to the bucket instead of `./storage`.            |
| **Key rotation**      | `SERP_API_KEYS=a,b,c` · `GEMINI_API_KEYS=a,b,c`                                                                                    | Round-robins keys; advances to the next on quota/`429`/`401`.                           |
| **Remote browser**    | `STEEL_API_KEY=…` (Steel.dev) or `BROWSER_REMOTE_CDP_URL=wss://…` (Brightdata / Browserless)                                       | Run browser captures on a managed stealth-browser instead of a local Chrome — required to pass Cloudflare from a server. See below. |

Stand up the managed services:

* **Postgres** — use the pooled transaction endpoint (`*pooler.supabase.com:6543`). The
  engine disables psycopg3 prepared statements (required for pgbouncer transaction mode)
  and enables `pool_pre_ping`. The schema is created automatically and an in-place column
  migration runs at startup (use Alembic for anything heavier).
* **Supabase Storage** — create a bucket (e.g. `ai-tracker-storage`) and generate S3
  access keys (**Storage → Settings → S3 Access Keys**). The endpoint is derived from
  `SUPABASE_PROJECT_REF` (`https://<ref>.storage.supabase.co/storage/v1/s3`) or set
  `SUPABASE_S3_ENDPOINT` directly; `SUPABASE_S3_REGION` is the project region (e.g.
  `ap-northeast-1`). Artifacts land under `raw/ processed/ screenshots/ html/` keys and
  are served via presigned URLs, or public object URLs if the bucket is public and
  `SUPABASE_STORAGE_PUBLIC=true`. Verify connectivity with a write/read/delete
  round-trip: `python -m scripts.check_storage`.
* **Redis (broker)** — run it locally (e.g. via Homebrew):
  ```bash
  brew install redis
  brew services start redis        # Verify with: redis-cli ping → PONG
  ```

Then create the schema:

```bash
python -m scripts.init_db
```

##### 3. Provider auth status

All providers run **anonymously** — no login required.

| Provider         | Type    | Notes                                                                              |
| ---------------- | ------- | ---------------------------------------------------------------------------------- |
| `chatgpt`        | Browser | Anonymous `chatgpt.com`. Cloudflare Turnstile handled by patchright + stealth.     |
| `gemini`         | Browser | `gemini.google.com` allows signed-out queries; consent auto-dismissed.             |
| `perplexity`     | Browser | Anonymous `perplexity.ai`; citation-rich. Cloudflare handled by patchright.        |
| `google_ai`      | SerpAPI | Google AI Overview via SerpAPI (two-step `page_token`). Needs `SERP_API_KEY`.      |
| `google_ai_mode` | SerpAPI | Google AI Mode via SerpAPI (`engine=google_ai_mode`). Needs `SERP_API_KEY`.        |

Browser providers honor an optional `PROXY_URL` for proxy rotation. SerpAPI providers need no browser and never hit Cloudflare.

**Optional (Logged-in Sessions):** If you *want* to use a signed-in session (for higher ChatGPT rate limits, or Gemini features only available to logged-in users), run:

```bash
python -m scripts.login_provider chatgpt
python -m scripts.login_provider gemini
```

Cookies persist to `./.browser_profiles/<provider>/` and are reused automatically.

**Cloudflare / consent handling** — ChatGPT and Google Search sit behind Cloudflare
Turnstile, which detects automation frameworks at the **CDP (Chrome DevTools Protocol)**
level. We address this with:
* **patchright**: A patched version of `playwright` that hides CDP fingerprints (highly recommended).
* **Real Chrome** (`channel="chrome"`): Used preferentially if installed.
* **Persistent profile**: Cookies and clearance tokens survive between runs.
* **`HEADLESS=false`** (default in development): Pauses while any Turnstile challenge is solved.

**Running browser captures on a server** — local Chrome (above) is for dev. In the
cloud there's no display, the IP is a flagged datacenter range, and no human to solve a
challenge. Point the browser providers at a managed stealth-browser service instead — it
supplies residential IPs, stealth fingerprints, and CAPTCHA solving, and no local Chrome
window opens:

* **Steel.dev** (free tier): `pip install steel-sdk`, then set `STEEL_API_KEY`. A Steel
  session is created per capture. Reliability against Cloudflare is tiered:
  * `STEEL_PERSIST_PROFILE=true` (default, any plan) — reuses one profile per provider so
    a cleared challenge carries forward across runs. The main free-tier lever.
  * `STEEL_PROXY_URL=` — bring your own residential proxy (any plan).
  * `STEEL_USE_PROXY=true` / `STEEL_SOLVE_CAPTCHA=true` — Steel-managed proxy + CAPTCHA
    solving; **require a paid plan** (the free plan rejects them). The reliable path.
* **Brightdata / Browserless**: set `BROWSER_REMOTE_CDP_URL` to the service's `wss://` CDP
  endpoint instead.

SerpAPI providers (`google_ai`, `google_ai_mode`) need no browser and run server-side
as-is. Verify connectivity before a real run with `python -m scripts.check_browser`
(confirms connection only — actual Cloudflare bypass is proven by a real capture).

##### 4. (Optional) Seed example data

To view the dashboard with pre-populated graphs without waiting for a fresh capture run:

```bash
python -m scripts.seed_example
```

##### 5. Start the backend services (separate terminals)

```bash
# API
uvicorn backend.main:app --reload          # → http://127.0.0.1:8000

# Celery worker(s) — pass a count to run providers in parallel (see note below)
./scripts/worker.sh 3                        # 3 parallel solo workers
# ./scripts/worker.sh                        # 1 worker (sequential capture)
```

With the broker set, `POST /capture` returns immediately (`"mode": "celery"`) and the
workers perform the scrape + NLP.

**How the work is parallelised.** A capture batch is **fanned out one Celery task per
provider**, so providers (ChatGPT, Gemini, Perplexity, Google AI…) are scraped **in
parallel** across workers — within a single provider, prompts stay sequential to honor
rate limiting and the circuit breaker. When every provider task finishes, a single chord
callback runs the heavy NLP **sequentially**; inside each run, **NER and sentiment run on
two threads concurrently** (torch and spaCy both release the GIL). To actually get parallel
capture you need more than one worker process — `worker.sh N` launches `N` solo workers
(each `--pool=solo`, required on macOS to avoid PyTorch/Playwright fork-safety crashes).
The in-process fallback mode applies the same capture-parallel / process-sequential split
within one process.

> **Local fallback (backup option).** A zero-dependency mode is built in: leave
> `DATABASE_URL`, `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND`, and the `SUPABASE_*` vars
> **unset** and the app runs fully local — SQLite, local `./storage`, and in-process
> FastAPI background tasks (no Redis, no worker). Setup is just `python -m scripts.init_db`
> then `uvicorn backend.main:app --reload`; skip steps 2 and the worker in step 5.

#### Frontend

```bash
cd frontend
npm install
npm run dev
# → Dashboard running at http://localhost:5173
```

---

## Usage & Features

1. Open the dashboard at `http://localhost:5173`.
2. Create a project: name, domain, up to 5 prompts, and optional competitors.
3. Click **Run capture**. The backend launches browser instances, visits each provider, submits the prompt, captures the response, saves a full-page screenshot, and writes the raw response to the configured storage backend (local `storage/raw/`, or Supabase Storage in the scaled path).
4. The processing pipeline runs immediately after: spaCy NER → rapidfuzz normalization → mentions & citations persisted to the database.

### What gets stored per run

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

Raw data is immutable. Re-running the processing layer (via the **Reprocess** button or `POST /api/projects/{id}/reprocess`) re-runs entity extraction and metrics without initiating new browser scrapes.

### Sentiment & Framing (Local NLP)

Runs **entirely locally** using a HuggingFace model (`cardiffnlp/twitter-roberta-base-sentiment-latest` by default, configured via `SENTIMENT_MODEL`).
* **Sentiment**: Positive / Neutral / Negative.
* **Framing**: Leader / Also-ran / Cautionary / Not-mentioned.
* Toggle or disable via `ENABLE_SENTIMENT`. If HuggingFace dependencies are not installed, falls back gracefully to a lexicon ruleset.

### LLM Features (Gemini)

When `GEMINI_API_KEY` is provided, the dashboard unlocks:
* **Prompt suggestions**: Proposed industry-specific high-intent search queries.
* **Competitor auto-detection**: Auto-discovers and labels competitor brands in LLM outputs.

---

## System Configuration Details

### Caching, TTL & Resilience

| Concern | Setting | Behavior |
| :--- | :--- | :--- |
| **Capture Cache** | `CACHE_TTL_HOURS=24` | Reuses matching query captures within the threshold unless bypassed with `force_refresh`. |
| **Artifact TTL** | `ARTIFACT_TTL_DAYS=7` | Purges raw HTML, screenshot images, and JSONs older than 7 days. SQL stats are kept. |
| **Rate Limiting** | `PROVIDER_MIN_DELAY_SECONDS=3` | Minimum stagger delay between request executions per browser provider. |
| **Circuit Breaker** | `CIRCUIT_BREAKER_THRESHOLD=3` | Fails active captures fast if a provider goes down (3 sequential errors) to avoid blocking the queue. |

### Visibility Score Calculation

```
visibility_score =
   (prompts_where_brand_appears / total_prompts) * 100
   + first_mention_bonus            (up to 10 points)
   + min(citations, 5) * 2          (up to 10 points)
   + multi_provider_bonus           ((providers_seen - 1) * 5)
   → capped at 100
```

### Selector Maintenance
When AI layouts change, selectors will break. Reprocess raw logs to update analytics once new rules are defined in providers:
```bash
curl -X POST http://127.0.0.1:8000/api/projects/<id>/reprocess
```

---

## Tech Stack

* **Backend**: Python 3.12, FastAPI, Playwright (CDP stealth), SQLAlchemy 2, spaCy, rapidfuzz.
* **Frontend**: React 18, Vite, TailwindCSS, Recharts, shadcn components.
