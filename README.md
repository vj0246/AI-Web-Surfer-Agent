# Web Agent — Local Multi-Agent Research Assistant

A general-purpose AI web agent. Ask anything: it plans, searches, scrapes, and synthesizes a cited answer. Runs 100% locally. No cloud APIs, no cloud search.

A planner splits your question into distinct angles, parallel researcher agents investigate them at once, a critic checks whether the evidence is enough, and a synthesis model streams back a cited answer. You watch the whole thing happen: a live reasoning timeline on one side, a live browser (real Chromium, with a visible moving cursor) on the other.

**Inspired by Perplexity AI, built with open-source only.**

---

## Architecture

```
Query + History
      |
AnalyzeQuery (phi3:mini)         classify factual/news/code/direct, decompose sub-queries
      |
CacheCheck (ChromaDB)            cosine similarity + TTL; temporal queries always bypass
      |
  +--------------+
  | cache hit    |-> Synthesize -> END
  | direct       |-> DirectAnswer (llama3.1) -> END
  | needs web    |
  +--------------+
      |
Planner (phi3:mini)              expand into N distinct-angle search queries
      |
      +--> Researcher 1 -+
      +--> Researcher 2  |       parallel (LangGraph Send fan-out)
      +--> Researcher 3 -+       each: search -> scrape -> extract (relevance 0-10)
      |
Critic (phi3:mini)               enough coverage? if not, dispatch a bounded gap round
      |
BuildContext                     dedupe by domain, top-5, cite [N]; snippets backfill citations
      |
Synthesize (llama3.1:8b)         stream the cited answer -> StoreCache -> END
```

**Two-model strategy:** `phi3:mini` (3.8B, fast) handles planning, per-page extraction, and critique. `llama3.1:8b` handles final synthesis only. Combined with running the researchers in parallel, wall-clock time is roughly one researcher's latency, not the sum.

---

## Stack

| Layer | Tech |
|---|---|
| Local LLM | Ollama: phi3:mini + llama3.1:8b + nomic-embed-text |
| Agent framework | LangGraph (StateGraph with `Send` fan-out) |
| Web search | SearXNG (self-hosted meta-search: Google, Bing, Wikipedia, DuckDuckGo) |
| Scraper | Playwright async Chromium, headed, live JPEG frame streaming, visible cursor, IndiGo form automation |
| Vector cache | ChromaDB, cosine similarity, 30-min TTL |
| Backend | FastAPI + SSE streaming + WebSocket (live browser frames) |
| Frontend | React 19 + Vite, no UI library |

---

## What you see

- **Agent timeline (SSE):** every step streamed live: planner angles, each researcher's pages and relevance scores, the critic's verdict, then the answer typing itself.
- **Live browser (WebSocket):** real Chromium screenshots streamed to a panel, plus the actual headed window on your desktop. An injected cursor visibly glides to and clicks each field. For flight queries it fills the IndiGo search form.

---

## Prerequisites

- [Ollama](https://ollama.ai) installed and running
- Python 3.11+
- Node.js 20+
- Docker + Docker Compose (for SearXNG)

---

## Setup

### 1. Pull models

```bash
ollama pull phi3:mini
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

### 2. Start SearXNG

```bash
cd web-agent
docker compose up searxng -d

# verify
curl "http://localhost:8080/search?q=test&format=json" | python3 -m json.tool | head -20
```

### 3. Backend

```bash
cd web-agent/backend

pip install -e .
playwright install chromium

cp ../.env.example .env          # edit OLLAMA_HOST if not localhost

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Health check: `curl http://localhost:8000/health`

### 4. Frontend

```bash
cd web-agent/frontend

npm install
echo "VITE_BACKEND_API_URL=http://localhost:8000" > .env

npm run dev
```

Open: **http://localhost:3000**

### Tests

```bash
cd web-agent/backend
pip install -e ".[dev]"
pytest
```

---

## Full Docker Compose

Ollama must still run on the host machine.

```bash
cd web-agent
cp .env.example .env
docker compose up --build
```

---

## How the multi-agent flow works

For the query **"how does RLHF work?"**:

```
1. AnalyzeQuery -> type=factual, needs_web=true
                  sub_queries=["RLHF reinforcement learning", "RLHF LLM training"]

2. CacheCheck   -> miss (first time)

3. Planner      -> 3 distinct angles:
                  ["RLHF explained", "RLHF reward model training", "RLHF vs supervised fine-tuning"]

4. Send fan-out -> 3 researcher agents run in parallel, each:
                    search (SearXNG) -> scrape (Playwright, headed) -> extract (phi3:mini)
                    [openai.com] 9.2/10   [huggingface] 8.4/10   [arxiv] 8.1/10

5. Critic       -> 3 high-relevance extracts >= 2 needed -> PROCEED (no gap round)

6. BuildContext -> domain-deduplicated, top-5 by relevance, citations [1]..[5]
                   (if scraping was blocked, SearXNG snippets backfill the citations)

7. Synthesize (llama3.1:8b) -> streams the cited answer token by token
                   "RLHF works by... [1]  The stages are supervised fine-tuning [1],
                    reward model training [3], and PPO optimization [2]..."

8. StoreCache   -> embedded in ChromaDB for 30-min reuse
```

If the first round comes back thin (fewer than `MIN_RELEVANT_EXTRACTS` high-relevance extracts), the critic names the missing angles and dispatches one more bounded researcher round before synthesizing.

---

## Tuning

Set in `.env` (see `.env.example`).

| Config | Default | Effect |
|---|---|---|
| `MAX_RESEARCHERS` | 3 | Parallel researcher agents per round |
| `MAX_CRITIC_ROUNDS` | 1 | Extra gap-filling rounds the critic may trigger |
| `MAX_CONCURRENT_BROWSERS` | 2 | Simultaneous headed Chrome windows |
| `MAX_SCRAPE_PER_ITER` | 3 | URLs each researcher scrapes |
| `MIN_RELEVANT_EXTRACTS` | 2 | High-relevance extracts before the critic proceeds |
| `RELEVANCE_THRESHOLD` | 5.0 | Minimum score (0-10) to count as high-relevance |
| `MAX_CONTEXT_EXTRACTS` | 5 | Top-k sources passed to the synthesizer |
| `CACHE_TTL_SECONDS` | 1800 | 0 = disable; temporal queries always bypass |
| `SCRAPER_HEADLESS` | false | false = open a real Chrome window and watch the cursor surf |

---

## Known limitations

- Playwright is blocked by some sites (Amazon, Cloudflare). Headed mode helps; when a scrape is fully blocked the answer still stays grounded via SearXNG snippet citations.
- Parallel researchers open up to `MAX_CONCURRENT_BROWSERS` headed Chrome windows at once, and their live frames interleave in the single browser panel. Set the cap to 1 for a calmer view.
- SearXNG relies on the underlying engines; if Google rate-limits its IP, result quality drops. Add engines in `searxng/settings.yml`.
- phi3:mini (3.8B) occasionally emits malformed JSON; every parser has a regex-extract plus a safe fallback so the pipeline never crashes.
- Session history is in-memory only; restarting the backend clears it. ChromaDB persists to disk.
