# Web Agent — Technical Documentation

Local-first AI research agent. You type a query, a team of local models plans the research, fans out parallel researcher agents that search the live web and scrape pages, a critic checks whether the evidence is sufficient, and a synthesis model streams back a cited answer. Everything runs on your own machine. No cloud LLM APIs, no cloud search.

Two live views run side by side. The right-hand "Agent steps" panel is the reasoning timeline: it streams every decision the agent team makes (analyze, plan, each researcher, critic, synthesize). The live browser panel shows real Chromium screenshots streamed over a WebSocket, so you watch the pages actually load and, for flight queries, watch a booking form get filled in.

---

## 1. What this project actually is

A multi-agent research pipeline built as a stateful LangGraph graph. A **planner** decomposes the query into distinct research angles; one **researcher agent per angle** runs in parallel (search → scrape → extract) via LangGraph's `Send` fan-out; a **critic** fans them back in, judges coverage, and can dispatch a bounded second round to fill gaps; then a larger model **synthesizes** the final cited answer.

Two local Ollama models split the work: a small fast model handles routing, planning, extraction, and critique, and a larger model writes the final answer. SearXNG provides meta-search across many engines, Playwright does the scraping (headed, with live screenshot streaming), and ChromaDB caches answers by semantic similarity so repeat questions return instantly.

The headline difference from a plain chatbot: you see the agent team think and browse. Each step is emitted as a Server-Sent Event and rendered in the timeline; the browser panel streams the live page. The planner's angles, each researcher's relevance scores, the critic's verdict, and the final token stream are all visible as they happen.

---

## 2. Tech stack — exact components

| Layer | Component | Version / model | Role |
|---|---|---|---|
| Planner / researcher / critic / extraction LLM | Ollama `phi3:mini` | 3.8B | Query analysis, research planning, per-page extraction, coverage critique |
| Synthesis LLM | Ollama `llama3.1:8b` | 8B | Final answer writing only |
| Embeddings | Ollama `nomic-embed-text` | — | Vectorizes queries for the semantic cache |
| Agent framework | LangGraph | StateGraph + `Send` fan-out | Stateful graph with parallel map-reduce over researchers |
| Web search | SearXNG | self-hosted | Meta-search over Google, Bing, Wikipedia, DuckDuckGo |
| Scraper | Playwright (async, Chromium, headed) | — | Loads pages, streams screenshots, form-automates IndiGo |
| Vector cache | ChromaDB | PersistentClient, cosine | 30-min TTL semantic answer cache |
| Backend | FastAPI + `sse-starlette` + WebSocket | — | REST + SSE token streaming + live browser frames |
| Frontend | React 19 + Vite 7 | no UI library | Chat UI, agent timeline, live browser panel |
| Config | pydantic-settings | — | Env-driven settings |
| Containers | Docker Compose | — | Runs backend, frontend, SearXNG together |

Models are addressed by name from `app/core/config.py`. Ollama itself runs on the host (the backend talks to it at `http://localhost:11434`, or `host.docker.internal` inside Docker). `phi3:mini` fills the `planner_model` slot and does all the fast structured-JSON work; `llama3.1:8b` is the `synthesizer_model`.

---

## 3. Backend code map

```
backend/app/
├── main.py                  FastAPI app, CORS, /health, mounts chat + browser_ws routers
├── core/config.py           pydantic Settings — every tunable lives here
├── models/core.py           Pydantic models: SearchHit, PageExtract, Citation, QueryAnalysis…
├── api/
│   ├── chat.py              POST /api/chat/stream (SSE), DELETE /api/chat/session/{id}
│   └── browser_ws.py        WS /ws/browser/{session_id} — live screenshot frames
├── pipeline/
│   ├── graph.py             LangGraph wiring: nodes, Send fan-out, routers
│   ├── state.py             AgentState TypedDict (shared state + reducer channels)
│   └── nodes.py             one async function per graph node
└── services/
    ├── query_analyzer.py    classify + decompose the query (phi3:mini)
    ├── orchestrator.py      planner (plan_research) + critic (critique_coverage) (phi3:mini)
    ├── cache.py             ChromaDB lookup / store
    ├── embedder.py          nomic-embed-text wrapper
    ├── searxng.py           search() + multi_search() against SearXNG
    ├── scraper.py           Playwright scrape_all() + IndiGo form automation + frame streaming
    ├── browser_channel.py   thread-safe per-session frame queue (scraper threads → WS)
    ├── flight_utils.py      flight-query detection, IATA/date parsing, reliable-URL building
    ├── content_extractor.py per-page relevance extraction (phi3:mini)
    ├── context_builder.py   dedupe by domain, rank, truncate, build citations
    ├── synthesizer.py       streaming final answer (llama3.1:8b)
    └── session_store.py     in-memory per-session history window
```

The live code is everything under `backend/app/` and `frontend/src/`. (Earlier `_backup`, `_extra`, and the legacy `react_reasoner.py` from the single-loop design have been removed.)

---

## 4. The pipeline, node by node

The graph is a LangGraph `StateGraph`. State is a single `AgentState` dict that every node reads from and writes partial updates to. List fields marked `Annotated[..., operator.add]` accumulate across nodes and across the **parallel researchers** instead of being overwritten — this is how page extracts and per-researcher results from concurrent agents merge safely.

1. **analyze_query** — `phi3:mini` classifies the query into one of `factual / howto / news / comparison / code / direct`, decides `needs_web`, decomposes it into 1–3 sub-queries, and flags `is_temporal` (a regex also catches words like "latest", "today", "2026"). A force-web regex overrides the model for price/travel/news topics it tends to mislabel. Temporal queries bypass the cache.

2. **check_cache** — embeds the query with `nomic-embed-text`, runs a cosine query against ChromaDB filtered to entries newer than the TTL. If the nearest neighbour is within `cache_similarity_threshold` (0.12), it is a hit and the stored answer is reused. Temporal queries skip this entirely.

3. **Cache router** decides the path:
   - cache hit → straight to `synthesize` (returns the cached answer)
   - `needs_web == false` → `direct_answer` (model answers from its own knowledge, no web)
   - otherwise → `plan`

4. **plan** (planner agent) — `phi3:mini` (`orchestrator.plan_research`) expands the query into up to `max_researchers` (3) **distinct-angle** search queries, each attacking a different facet (definition, mechanism, comparison, recent developments, examples). For **flight queries** it instead uses `flight_utils.build_flight_search_queries`, and marks researcher 0 to drive IndiGo form automation. Output is a `research_tasks` list. On JSON-parse failure it falls back to the analyzer's sub-queries.

5. **Dispatch (Send fan-out)** — a conditional edge turns each task into a `Send("research", {...})`, launching **one researcher agent per task in parallel**. Each `Send` payload carries the sub-query, the main query, the session id, and the flight flag; the researcher receives only that payload as its state.

6. **research** (researcher agent, runs in parallel, one per angle) —
   - `search(sub_query)` against SearXNG → top `max_scrape_per_iter` (3) URLs.
   - Flight-flagged researcher prepends reliable flight URLs (IndiGo homepage, Cleartrip/SpiceJet search).
   - `scrape_all(...)` loads the URLs in a headed Chromium (bounded by `max_concurrent_browsers`), streaming screenshots to the browser panel; the IndiGo homepage triggers full search-form automation.
   - `extract_pages_parallel(...)` runs `phi3:mini` per page against the **main** query to pull `relevant_text`, 3–5 `key_facts`, and a `relevance_score` (0–10). Junk/bot-blocked pages short-circuit to score 0 with no LLM call.
   - Returns only reducer channels (`page_extracts`, `search_hits`, `researcher_results`, `errors`) so concurrent researchers never collide on a plain field.

7. **critic** (fan-in) — all researchers merge here. `phi3:mini` (`orchestrator.critique_coverage`) is consulted only if fewer than `min_relevant_extracts` (2) high-relevance extracts exist. It either declares coverage sufficient → proceed, or names up to `max_researchers` gap queries and dispatches a **second research round**. The loop is bounded by `max_critic_rounds` (1), after which it always proceeds. This guarantees termination.

8. **build_context** — sorts all extracts by relevance, keeps at most one per domain, takes the top `max_context_extracts` (5), truncates to `max_context_chars` (6000), and appends SearXNG snippets if budget remains. Builds numbered citations `[1]…[5]`.

9. **synthesize** — `llama3.1:8b` writes the answer from the context only, citing inline as `[N]`. This streams token by token to the browser. With no context (direct path), it answers conversationally instead.

10. **store_cache** — embeds the query and upserts `{answer, citations, page_extracts}` into ChromaDB with a timestamp, unless the query was temporal or already a cache hit.

### Routing summary

| From | Condition | Goes to |
|---|---|---|
| check_cache | cache hit | synthesize |
| check_cache | no web needed | direct_answer |
| check_cache | needs web | plan |
| plan | has tasks | `Send` → N × research (parallel) |
| plan | no tasks | build_context |
| research | always (fan-in) | critic |
| critic | coverage sufficient / rounds exhausted | build_context |
| critic | gaps found, rounds left | `Send` → M × research (parallel) |
| build_context / direct_answer | always | synthesize → store_cache → END |

---

## 5. Why the model split and the fan-out make it fast

`phi3:mini` is small enough to handle the many quick structured-JSON calls (analysis, planning, every page extraction, critique) with low latency. `llama3.1:8b` is reserved for the single job where quality matters most, the final synthesis.

On top of that, the researchers run **concurrently** rather than as a serial search→scrape→reason loop: three angles are investigated at once, so wall-clock time is roughly one researcher's latency, not three. Browser concurrency is capped by `max_concurrent_browsers` so parallel headed Chrome windows don't thrash the machine.

---

## 6. The streaming layer (how the panels update live)

**Timeline (SSE).** The frontend opens one POST to `/api/chat/stream` and reads an SSE body. The backend uses `pipeline.astream(...)`, so each node completion emits an event. Because a single super-step can complete **several researcher nodes at once**, `chat.py` iterates every node in each streamed chunk. It maps node names to friendly event types:

`analyzing · cache_check · planning · researching · critiquing · building · synthesizing · token · done · error`

Most events carry a small `data` payload: the planner's angles, each researcher's sub-query with its page/relevance counts and scraped domains, the critic's verdict and round. The `synthesize` node is special: instead of one event, the backend streams the model's output token by token as `token` events. A final `done` event carries the full answer, citations, and any errors.

**Live browser (WebSocket).** The scraper runs in worker threads with their own event loops. It captures JPEG screenshots and pushes them onto a thread-safe per-session queue (`browser_channel.py`). The WebSocket endpoint `/ws/browser/{session_id}` (`browser_ws.py`) polls that queue and forwards frames to the browser panel, which swaps the `<img>` `src` directly (no React re-render per frame). Frame messages are typed `url` (navigation start), `frame` (screenshot), `idle`, and `error`.

On the React side, `useAgentStream.js` parses the SSE lines, `useChatSession.js` appends each event to that message's `timeline` array, `ReActTimeline.jsx` renders the steps (planner angles, per-researcher cards, critic badge, color-coded relevance), and `BrowserPanel.jsx` owns the WebSocket and the live frame.

---

## 7. Key configuration knobs

All in `app/core/config.py`, override via `.env`.

| Setting | Default | Effect |
|---|---|---|
| `planner_model` | phi3:mini | Analysis / planning / extraction / critique model |
| `synthesizer_model` | llama3.1:8b | Final answer model |
| `searxng_engines` | google,bing,wikipedia,duckduckgo | Which engines SearXNG queries |
| `searxng_results` | 10 | Hits returned per search |
| `max_researchers` | 3 | Parallel researcher agents fanned out per round |
| `max_critic_rounds` | 1 | Extra gap-filling rounds the critic may trigger |
| `max_concurrent_browsers` | 2 | Cap on simultaneous headed Chrome windows |
| `max_scrape_per_iter` | 3 | URLs each researcher scrapes |
| `min_relevant_extracts` | 2 | High-relevance extracts before the critic proceeds without critiquing |
| `relevance_threshold` | 5.0 | Score (0–10) that counts as "relevant" |
| `max_context_extracts` | 5 | Top-k extracts passed to the synthesizer |
| `max_context_chars` | 6000 | Total context size cap |
| `cache_ttl_seconds` | 1800 | Cache lifetime; temporal queries always bypass |
| `cache_similarity_threshold` | 0.12 | Max cosine distance for a cache hit |
| `scraper_headless` | true | Set false to watch the browser surf live |
| `scraper_min/max_delay_ms` | 1500 / 3500 | Randomized per-page delay (politeness + anti-bot) |
| `session_max_turns` | 8 | Conversation turns kept in the prompt history window |

`max_iterations` still exists for backward compatibility but no longer drives control flow — the planner/critic rounds replaced the old single-loop iteration counter.

---

## 8. API surface

- `POST /api/chat/stream` — body `{ query, session_id? }`. Returns an SSE stream of pipeline events and answer tokens. A new `session_id` is generated if omitted.
- `WS /ws/browser/{session_id}` — live browser frames (`url` / `frame` / `idle` / `error` messages) for the session's scraping.
- `DELETE /api/chat/session/{session_id}` — clears that session's in-memory history.
- `GET /health` — liveness check.

Sessions are in-memory only (a thread-safe `OrderedDict` with a sliding window and a 1000-session cap). Restarting the backend clears all history. ChromaDB, by contrast, persists to disk.

---

## 9. Setup

Prerequisites: Ollama running on the host, Python 3.11+, Node 20+, Docker + Compose.

```bash
# 1. Pull models
ollama pull phi3:mini
ollama pull llama3.1:8b
ollama pull nomic-embed-text

# 2. Start SearXNG
cd web-agent
docker compose up searxng -d

# 3. Backend
cd backend
pip install -e .
playwright install chromium
cp ../.env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 4. Frontend
cd ../frontend
npm install
echo "VITE_BACKEND_API_URL=http://localhost:8000" > .env
npm run dev      # opens on http://localhost:3000
```

Full stack in one go (Ollama still on host): `docker compose up --build`.

---

## 10. Known limitations

- Playwright is blocked by some sites (Amazon, heavy Cloudflare). `SCRAPER_HEADLESS=false` helps and also lets you watch the surfing. Flight booking sites are handled via a curated reliable-URL list (`flight_utils.py`) plus IndiGo form automation.
- Parallel researchers open up to `max_concurrent_browsers` headed Chrome windows at once; their live frames interleave in the single browser panel. Set the cap to 1 for a calmer view.
- SearXNG depends on the upstream engines; if Google rate-limits its IP, result quality drops. Add more engines in `searxng/settings.yml`.
- `phi3:mini` occasionally emits malformed JSON on planning/extraction/critique; every parser has a regex-extract plus a safe fallback so the pipeline never crashes on it.
- The critic is bounded to `max_critic_rounds` extra rounds — it will synthesize with partial evidence rather than loop forever.
- Session history is in-memory; a restart wipes it.
- The live page view is real non-headless Chromium screenshots streamed as JPEG frames, not a fully interactive remote browser.

---

## 11. One concrete trace

Query: *"how does RLHF work?"*

```
analyze     → factual, needs_web=true, sub_queries=[RLHF reinforcement learning human feedback, RLHF LLM training]
cache       → miss
plan        → 3 angles: [what is RLHF + reward model, RLHF vs supervised fine-tuning, RLHF training steps PPO]
dispatch    → Send × 3 researchers (parallel)
  research A → search → scrape 3 → extract: openai 9.2/10, huggingface 8.4/10
  research B → search → scrape 3 → extract: wikipedia 7.8/10, arxiv 8.1/10
  research C → search → scrape 3 → extract: blog 6.5/10, docs 7.0/10
critic      → 6 high-relevance ≥ 2 needed → PROCEED (no gap round)
build       → dedupe by domain, top-5, 6000-char cap, citations [1]…[5]
synthesize  → llama3.1:8b streams the cited answer token by token
cache       → stored in ChromaDB for 30 min
```

If the first round had come back thin (fewer than 2 high-relevance extracts), the critic would have named the missing angles and dispatched a second `Send × M` researcher round before synthesizing.
