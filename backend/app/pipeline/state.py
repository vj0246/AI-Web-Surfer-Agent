import operator
from typing import Annotated, TypedDict


class AgentState(TypedDict):
    # ── session ──────────────────────────────────────────────
    session_id: str
    query: str
    history_text: str           # formatted conversation history for prompts

    # ── query analysis (set once) ────────────────────────────
    query_type: str             # "factual" | "howto" | "news" | "comparison" | "code" | "direct"
    needs_web: bool
    sub_queries: list[str]      # 1-3 decomposed search queries
    is_temporal: bool           # bypass cache if true

    # ── accumulators (Annotated → LangGraph appends across parallel researchers) ──
    search_hits: Annotated[list[dict], operator.add]    # all SearchHit dicts
    page_extracts: Annotated[list[dict], operator.add]  # all PageExtract dicts
    errors: Annotated[list[str], operator.add]          # all error messages

    # ── multi-agent orchestration ────────────────────────────
    # researcher_results is a reducer: parallel researcher agents append concurrently
    researcher_results: Annotated[list[dict], operator.add]  # per-researcher summaries
    research_tasks: list[dict]   # [{sub_query, inject_flight}] dispatched this round (overwritten per round)
    plan_summary: list[str]      # planner's chosen research angles (for the timeline)
    critic_round: int            # how many gap-filling rounds the critic has triggered
    critic_done: bool            # True once coverage is sufficient or rounds exhausted
    critic_note: str             # critic's human-readable verdict for the timeline

    # ── cache ─────────────────────────────────────────────────
    cache_hit: bool

    # ── output ────────────────────────────────────────────────
    synthesis_context: str
    answer: str
    citations: list[dict]       # [{index, url, title, snippet}]
