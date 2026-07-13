# Web Agent v0.2 — Local AI ReAct Research Assistant

A general-purpose AI web agent. Ask anything — it reasons, searches, scrapes, and synthesizes a cited answer. Runs 100% locally. No cloud APIs.

**Inspired by Perplexity AI, built with open-source only.**

---

## Architecture

```
Query + History
      ↓
AnalyzeQuery (phi3:mini)         ← classify: factual/news/code/direct, decompose sub-queries
      ↓
CacheCheck (ChromaDB)            ← cosine similarity + TTL; temporal queries always bypass
      ↓
  ┌──────────────┐
  │ cache hit    │→ Synthesize → END
  │ direct       │→ DirectAnswer (llama3.1) → END
  │ needs web    ↓
  └──────────────┘
ReActReasoner (phi3:mini) ◄──────────────────────────┐
  │ SEARCH → SearXNG → RankURLs ──────────────────────┘ (loop)
  │ SCRAPE → Playwright (parallel) → ContentExtractor ─┘ (loop)
  └ DONE   → BuildContext → Synthesizer (llama3.1:8b) → StoreCache → END
```

**Two-model strategy:** phi3:mini (3.8B, fast) handles routing, extraction, and ReAct reasoning. llama3.1:8b handles final synthesis only. ~3× faster than single-model.

---

## Stack

| Layer | Tech |
|---|---|
| Local LLM | Ollama — phi3:mini + llama3.1:8b + nomic-embed-text |
| Agent framework | LangGraph (stateful cyclic graph) |
| Web search | SearXNG (self-hosted meta-search — Google, Bing, Wikipedia, DDG, SO, arXiv, Reddit) |
| Scraper | Playwright async, user-agent rotation, scroll simulation |
| Vector cache | ChromaDB, cosine similarity, 30-min TTL |
| Backend | FastAPI + SSE streaming |
| Frontend | React + Vite, no UI library |

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

---

## Full Docker Compose

Ollama must still run on the host machine.

```bash
cd web-agent
cp .env.example .env
docker compose up --build
```

---

## How the ReAct loop works

For the query **"how does RLHF work?"**:

```
1. AnalyzeQuery → type=factual, needs_web=true
                  sub_queries=["RLHF reinforcement learning", "RLHF LLM training"]

2. CacheCheck   → miss (first time)

3. ReActReason  → thought: "No searches yet, must start with SEARCH"
                  action: SEARCH, query: "RLHF reinforcement learning"

4. SearXNG      → 10 results from Google + Wikipedia + arXiv

5. RankURLs     → top 3 unscraped URLs selected

6. ReActReason  → thought: "Have URLs but only snippets, need full content"
                  action: SCRAPE, url: "openai.com/blog/..."

7. Playwright   → async scrape 3 pages in parallel

8. ContentExtractor (phi3:mini per page) →
   [openai.com] relevance: 9.2/10, key_facts: [...]
   [wikipedia]  relevance: 7.8/10, key_facts: [...]
   [arxiv]      relevance: 8.1/10, key_facts: [...]

9. ReActReason  → thought: "3 high-relevance extracts, enough to answer"
                  action: DONE

10. BuildContext → domain-deduplicated, top-5 by relevance, truncated to 6000 chars

11. Synthesizer (llama3.1:8b) →
    "RLHF (Reinforcement Learning from Human Feedback) works by... [1][2]
     The key stages are: 1) supervised fine-tuning... [1]
     2) reward model training... [3]..."

12. StoreCache → embedded in ChromaDB for 30-min reuse
```

---

## Tuning

| Config | Default | Effect |
|---|---|---|
| `MAX_ITERATIONS` | 3 | Max search/scrape cycles before forced synthesis |
| `MIN_RELEVANT_EXTRACTS` | 2 | Extracts with score ≥ threshold before DONE allowed |
| `RELEVANCE_THRESHOLD` | 5.0 | Minimum score (0-10) to count as high-relevance |
| `CACHE_TTL_SECONDS` | 1800 | 0 = disable; temporal queries always bypass |
| `MAX_CONTEXT_EXTRACTS` | 5 | Top-k extracts passed to synthesizer |
| `SCRAPER_HEADLESS` | true | Set false if sites block headless Chromium |

---

## Known limitations

- Playwright may be blocked by some sites (Amazon, Cloudflare-protected). Set `SCRAPER_HEADLESS=false` as fallback.
- SearXNG relies on underlying search engines — if Google blocks SearXNG's IP, results drop. Add more engines in `searxng/settings.yml`.
- phi3:mini (3.8B) occasionally produces malformed JSON on complex extraction prompts — the code handles this gracefully with fallbacks.
- Session history is in-memory only — restarts clear all sessions.
