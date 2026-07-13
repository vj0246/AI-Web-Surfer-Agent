"""
nodes.py v0.4 — multi-agent orchestration.

Flow: analyze -> cache -> plan -> [parallel researchers] -> critic -> build -> synthesize -> cache.
The planner fans out one researcher agent per angle via LangGraph Send(). Each researcher
runs search -> scrape -> extract on its own. The critic checks coverage and may dispatch a
bounded second round to fill gaps. build_context / synthesize / store_cache are unchanged.
"""
from app.core.config import settings
from app.pipeline.state import AgentState
from app.services.cache import cache_lookup, cache_store
from app.services.content_extractor import extract_pages_parallel
from app.services.context_builder import build_context
from app.services.flight_utils import build_flight_search_queries, build_flight_urls, extract_flight_params
from app.services.orchestrator import critique_coverage, plan_research
from app.services.query_analyzer import analyze_query
from app.services.scraper import scrape_all
from app.services.searxng import search
from app.services.synthesizer import synthesize_direct_full, synthesize_full


def _high_relevance_count(page_extracts: list[dict]) -> int:
    return sum(
        1 for e in page_extracts
        if e.get("relevance_score", 0) >= settings.relevance_threshold
    )


# ─────────────────────────────────────────────────────────────────────────────
# Query analysis + cache + direct answer (unchanged behaviour)
# ─────────────────────────────────────────────────────────────────────────────

async def node_analyze_query(state: AgentState) -> dict:
    analysis = await analyze_query(state["query"], state.get("history_text", ""))
    return {
        "query_type": analysis.query_type,
        "needs_web": analysis.needs_web,
        "sub_queries": analysis.sub_queries,
        "is_temporal": analysis.is_temporal,
        "iteration": 0,
        "max_iterations": settings.max_iterations,
        "action": "",
        "action_params": {},
        "thought": "",
        "observations": [],
        "search_hits": [],
        "page_extracts": [],
        "errors": [],
        "scraped_urls": [],
        "ranked_urls": [],
        "cache_hit": False,
        "synthesis_context": "",
        "answer": "",
        "citations": [],
        # multi-agent fields
        "researcher_results": [],
        "research_tasks": [],
        "plan_summary": [],
        "critic_round": 0,
        "critic_done": False,
        "critic_note": "",
    }


async def node_check_cache(state: AgentState) -> dict:
    ttl = 0 if state.get("is_temporal") else None
    cached = await cache_lookup(state["query"], ttl_override=ttl)
    if cached:
        return {
            "cache_hit": True,
            "answer": cached.get("answer", ""),
            "citations": cached.get("citations", []),
            "page_extracts": cached.get("page_extracts", []),
        }
    return {"cache_hit": False, "answer": "", "citations": []}


async def node_direct_answer(state: AgentState) -> dict:
    answer = await synthesize_direct_full(state["query"], state.get("history_text", ""))
    return {"answer": answer, "citations": []}


# ─────────────────────────────────────────────────────────────────────────────
# Planner — decompose into distinct research angles (one researcher each)
# ─────────────────────────────────────────────────────────────────────────────

async def node_plan(state: AgentState) -> dict:
    query = state["query"]
    fp = extract_flight_params(query)

    if fp:
        # Flight queries get their own specialised angles; researcher 0 drives IndiGo automation.
        subs = build_flight_search_queries(fp)[: settings.max_researchers]
    else:
        subs = await plan_research(query, state.get("sub_queries", []), state.get("history_text", ""))

    subs = subs[: settings.max_researchers] or [query]
    tasks = [
        {"sub_query": s, "inject_flight": bool(fp) and i == 0}
        for i, s in enumerate(subs)
    ]
    return {"research_tasks": tasks, "plan_summary": subs, "critic_round": 0, "critic_done": False}


# ─────────────────────────────────────────────────────────────────────────────
# Researcher — Send worker. One instance per task, runs in parallel.
# Receives only its Send payload as state; writes to reducer channels.
# ─────────────────────────────────────────────────────────────────────────────

async def node_research(payload: dict) -> dict:
    main_query = payload["query"]
    sub_query = payload["sub_query"]
    session_id = payload.get("session_id", "")
    fp = extract_flight_params(main_query) if payload.get("inject_flight") else None

    hits = await search(sub_query)
    hit_dicts = [h.model_dump() for h in hits]

    urls = [h.url for h in hits[: settings.max_scrape_per_iter]]
    if fp:
        flight_urls = build_flight_urls(fp)
        urls = (flight_urls + [u for u in urls if u not in set(flight_urls)])[: settings.max_scrape_per_iter]

    scrape_results = await scrape_all(urls, session_id=session_id, flight_params=fp)
    scraped_now = {u for u, _, _ in scrape_results}
    html_results = [(u, html) for u, html, _ in scrape_results]

    extracts = await extract_pages_parallel(html_results, main_query)
    extract_dicts = [e.model_dump() for e in extracts]
    high = sum(1 for e in extracts if e.relevance_score >= settings.relevance_threshold)

    result = {
        "sub_query": sub_query,
        "urls": list(scraped_now),
        "extracted": len(extracts),
        "high_relevance": high,
    }
    errors = [f"scrape failed: {u}" for u in urls if u not in scraped_now]

    # Only reducer channels here — parallel researchers write concurrently.
    return {
        "page_extracts": extract_dicts,
        "search_hits": hit_dicts,
        "researcher_results": [result],
        "errors": errors,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Critic — fan-in. Judge coverage; optionally dispatch a bounded gap round.
# ─────────────────────────────────────────────────────────────────────────────

async def node_critic(state: AgentState) -> dict:
    extracts = state.get("page_extracts", [])
    high = _high_relevance_count(extracts)
    rnd = state.get("critic_round", 0)

    if high >= settings.min_relevant_extracts or rnd >= settings.max_critic_rounds:
        note = (
            f"Coverage sufficient ({high} high-relevance)."
            if high >= settings.min_relevant_extracts
            else f"Round limit reached ({rnd}/{settings.max_critic_rounds}); synthesizing with what we have."
        )
        return {"critic_done": True, "critic_note": note, "critic_round": rnd}

    gaps = await critique_coverage(
        state["query"], extracts, state.get("researcher_results", []), state.get("history_text", "")
    )
    if not gaps:
        return {"critic_done": True, "critic_note": "No further gaps identified.", "critic_round": rnd}

    tasks = [{"sub_query": g, "inject_flight": False} for g in gaps[: settings.max_researchers]]
    return {
        "critic_done": False,
        "research_tasks": tasks,
        "critic_round": rnd + 1,
        "critic_note": f"Gaps found ({high} high-relevance so far); dispatching {len(tasks)} more researchers.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Context build + synthesis + cache store (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

def node_build_context(state: AgentState) -> dict:
    context, citations = build_context(
        state.get("page_extracts", []),
        search_hits=state.get("search_hits", []),
    )
    return {"synthesis_context": context, "citations": [c.model_dump() for c in citations]}


async def node_synthesize(state: AgentState) -> dict:
    if state.get("cache_hit"):
        return {"answer": state.get("answer", ""), "citations": state.get("citations", [])}
    context = state.get("synthesis_context", "")
    fn = synthesize_full if context else synthesize_direct_full
    args = (state["query"], context, state.get("history_text", "")) if context \
        else (state["query"], state.get("history_text", ""))
    answer = await fn(*args)
    return {"answer": answer}


async def node_store_cache(state: AgentState) -> dict:
    if state.get("cache_hit") or state.get("is_temporal"):
        return {"answer": state.get("answer", "")}
    await cache_store(state["query"], {
        "answer": state.get("answer", ""),
        "citations": state.get("citations", []),
        "page_extracts": state.get("page_extracts", []),
    })
    return {"answer": state.get("answer", "")}
