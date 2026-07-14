"""Drive the multi-agent graph with every external service mocked.
No Ollama, SearXNG, Playwright, or ChromaDB required."""
import asyncio
import sys

import pytest

import app.pipeline.nodes as nodes
from app.models.core import PageExtract, QueryAnalysis, SearchHit
from app.pipeline.graph import build_pipeline

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def _initial(query):
    return {
        "session_id": "test", "query": query, "history_text": "",
        "query_type": "", "needs_web": True, "sub_queries": [], "is_temporal": False,
        "search_hits": [], "page_extracts": [], "errors": [], "cache_hit": False,
        "synthesis_context": "", "answer": "", "citations": [],
        "researcher_results": [], "research_tasks": [], "plan_summary": [],
        "critic_round": 0, "critic_done": False, "critic_note": "",
    }


def _patch(monkeypatch, extract_score, gaps):
    async def fake_analyze(query, history):
        return QueryAnalysis(query_type="factual", needs_web=True,
                             sub_queries=["a", "b", "c"], is_temporal=False)

    async def fake_cache_lookup(query, ttl_override=None):
        return None

    async def fake_cache_store(query, payload):
        return None

    async def fake_plan(query, subs, history):
        return ["angle 1", "angle 2", "angle 3"]

    async def fake_search(q, extra_engines=None):
        return [SearchHit(url=f"http://ex.com/{q.replace(' ', '_')}", title=q, snippet="s", score=1.0)]

    async def fake_scrape_all(urls, session_id="", flight_params=None):
        return [(u, f"<html>{u}</html>", "") for u in urls]

    async def fake_extract(scrape_results, query):
        return [PageExtract(url=u, title=f"T {u}", relevant_text="text",
                            key_facts=["f1", "f2"], relevance_score=extract_score)
                for u, _ in scrape_results]

    async def fake_critique(query, extracts, results, history):
        return list(gaps)

    async def fake_synth_full(query, context, history):
        return f"ANSWER from {len(context)} chars of context"

    monkeypatch.setattr(nodes, "analyze_query", fake_analyze)
    monkeypatch.setattr(nodes, "cache_lookup", fake_cache_lookup)
    monkeypatch.setattr(nodes, "cache_store", fake_cache_store)
    monkeypatch.setattr(nodes, "plan_research", fake_plan)
    monkeypatch.setattr(nodes, "search", fake_search)
    monkeypatch.setattr(nodes, "scrape_all", fake_scrape_all)
    monkeypatch.setattr(nodes, "extract_pages_parallel", fake_extract)
    monkeypatch.setattr(nodes, "critique_coverage", fake_critique)
    monkeypatch.setattr(nodes, "synthesize_full", fake_synth_full)


def test_full_flow_covered_in_one_round(monkeypatch):
    _patch(monkeypatch, extract_score=9.0, gaps=[])
    pipe = build_pipeline()
    out = asyncio.run(pipe.ainvoke(_initial("how does X work"), config={"recursion_limit": 100}))
    assert len(out["researcher_results"]) == 3       # planner fanned out 3 researchers
    assert out["critic_done"] is True
    assert out["critic_round"] == 0                   # no gap round needed
    assert out["answer"].startswith("ANSWER")
    assert len(out["citations"]) >= 1


def test_critic_dispatches_bounded_gap_round(monkeypatch):
    # low relevance -> critic finds gaps -> 2nd round -> hits round cap -> terminates
    _patch(monkeypatch, extract_score=1.0, gaps=["gap 1", "gap 2"])
    pipe = build_pipeline()
    out = asyncio.run(pipe.ainvoke(_initial("obscure question"), config={"recursion_limit": 100}))
    assert len(out["researcher_results"]) == 5        # 3 first round + 2 gap round
    assert out["critic_round"] == 1
    assert out["critic_done"] is True
    assert out["answer"].startswith("ANSWER")


def test_cache_hit_short_circuits(monkeypatch):
    _patch(monkeypatch, extract_score=9.0, gaps=[])

    async def hit(query, ttl_override=None):
        return {"answer": "CACHED", "citations": [{"index": 1, "url": "u", "title": "t"}], "page_extracts": []}

    monkeypatch.setattr(nodes, "cache_lookup", hit)
    pipe = build_pipeline()
    out = asyncio.run(pipe.ainvoke(_initial("repeat query"), config={"recursion_limit": 100}))
    assert out["cache_hit"] is True
    assert out["answer"] == "CACHED"
    assert len(out["researcher_results"]) == 0        # web path skipped entirely


def test_direct_answer_when_no_web(monkeypatch):
    _patch(monkeypatch, extract_score=9.0, gaps=[])

    async def no_web(query, history):
        return QueryAnalysis(query_type="direct", needs_web=False, sub_queries=[], is_temporal=False)

    async def fake_direct(query, history):
        return "DIRECT ANSWER"

    monkeypatch.setattr(nodes, "analyze_query", no_web)
    monkeypatch.setattr(nodes, "synthesize_direct_full", fake_direct)
    pipe = build_pipeline()
    out = asyncio.run(pipe.ainvoke(_initial("what is 2+2"), config={"recursion_limit": 100}))
    assert out["answer"] == "DIRECT ANSWER"
    assert len(out["researcher_results"]) == 0
