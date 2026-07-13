"""
orchestrator.py — planner + critic for the multi-agent pipeline.

plan_research()     : expand the query into distinct research angles (one per researcher agent).
critique_coverage() : after researchers report back, decide COVERED or name the gaps to re-dispatch.

Both use the fast planner_model. Every parse has a regex-extract + safe fallback so the
graph never crashes on malformed JSON (phi3:mini occasionally emits it).
"""
import json
import re

import ollama

from app.core.config import settings

_PLAN_PROMPT = """You are the planner for a research agent. Break the question into distinct search angles.

Question: "{query}"

Existing sub-queries (may be weak): {sub_queries}

Conversation history: {history_text}

Produce {n} DISTINCT search queries. Each must attack a DIFFERENT angle (definition,
mechanism, comparison, recent developments, concrete examples). No two may overlap.
Each query is concrete and self-contained (a search engine could answer it).

Return JSON only, no markdown:
{{"tasks": ["angle 1 search query", "angle 2 search query", "angle 3 search query"]}}"""

_CRITIC_PROMPT = """You are the critic for a research agent. Judge whether the gathered facts answer the question.

Question: "{query}"

Facts gathered so far:
{facts}

If the facts fully answer the question, return an empty gaps list.
If something important is MISSING, return up to {n} NEW search queries that would fill the gap.
Each gap query must target information NOT already covered above.

Return JSON only, no markdown:
{{"covered": true, "gaps": []}}
or
{{"covered": false, "gaps": ["missing-angle search query", "..."]}}"""


def _parse_json(raw: str) -> dict | None:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?", "", raw).rstrip("`").strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        raw = m.group()
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


async def plan_research(query: str, sub_queries: list[str], history_text: str) -> list[str]:
    """Return up to max_researchers distinct-angle search queries. Falls back to sub_queries."""
    n = settings.max_researchers
    fallback = (sub_queries or [query])[:n]

    prompt = _PLAN_PROMPT.format(
        query=query,
        sub_queries=", ".join(sub_queries) or "none",
        history_text=history_text or "None",
        n=n,
    )
    client = ollama.AsyncClient(host=settings.ollama_host)
    try:
        resp = await client.generate(model=settings.planner_model, prompt=prompt)
    except Exception as exc:
        print(f"[planner] generate error: {exc} -> fallback")
        return fallback

    data = _parse_json(resp["response"])
    if not data:
        print(f"[planner] parse failed -> fallback {fallback}")
        return fallback

    tasks = [str(t).strip() for t in data.get("tasks", []) if str(t).strip()]
    tasks = tasks[:n]
    if not tasks:
        return fallback
    print(f"[planner] query={query!r} -> {tasks}")
    return tasks


def _format_facts(page_extracts: list[dict], researcher_results: list[dict]) -> str:
    lines: list[str] = []
    for r in researcher_results:
        lines.append(
            f"- Researcher '{r.get('sub_query','?')}': "
            f"{r.get('extracted',0)} pages, {r.get('high_relevance',0)} high-relevance"
        )
    seen = 0
    for e in sorted(page_extracts, key=lambda x: x.get("relevance_score", 0), reverse=True):
        if e.get("relevance_score", 0) < settings.relevance_threshold:
            continue
        facts = "; ".join(e.get("key_facts", [])[:3])
        lines.append(f"  [{e.get('relevance_score',0)}/10] {e.get('title','')}: {facts}")
        seen += 1
        if seen >= 8:
            break
    return "\n".join(lines) or "No relevant facts gathered yet."


async def critique_coverage(
    query: str,
    page_extracts: list[dict],
    researcher_results: list[dict],
    history_text: str,
) -> list[str]:
    """Return a list of gap search queries (empty = coverage sufficient)."""
    n = settings.max_researchers
    prompt = _CRITIC_PROMPT.format(
        query=query,
        facts=_format_facts(page_extracts, researcher_results),
        n=n,
    )
    client = ollama.AsyncClient(host=settings.ollama_host)
    try:
        resp = await client.generate(model=settings.planner_model, prompt=prompt)
    except Exception as exc:
        print(f"[critic] generate error: {exc} -> no gaps")
        return []

    data = _parse_json(resp["response"])
    if not data or data.get("covered"):
        return []
    gaps = [str(g).strip() for g in data.get("gaps", []) if str(g).strip()]
    print(f"[critic] gaps={gaps}")
    return gaps[:n]
