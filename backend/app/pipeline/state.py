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

    # ── ReAct loop control ───────────────────────────────────
    iteration: int
    max_iterations: int
    action: str                 # current: "do_search" | "do_scrape" | "build_context"
    action_params: dict         # {query} or {url} for current action
    thought: str                # phi3:mini's current reasoning

    # ── accumulators (Annotated → LangGraph appends, not replaces) ──
    observations: Annotated[list[dict], operator.add]   # [{iteration, action, thought, result_summary}]
    search_hits: Annotated[list[dict], operator.add]    # all SearchHit dicts across iterations
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

    # ── mutable tracking ─────────────────────────────────────
    scraped_urls: list[str]     # already scraped (avoid re-scraping)
    ranked_urls: list[str]      # URLs ranked by current search hit ranking

    # ── cache ─────────────────────────────────────────────────
    cache_hit: bool

    # ── output (set by synthesizer) ──────────────────────────
    synthesis_context: str
    answer: str
    citations: list[dict]       # [{index, url, title, snippet}]
    _pending_scrape: list        # temp: (url, html) pairs passed to extractor
    page_screenshots: dict       # url → base64 jpeg screenshot from latest scrape

# temp scrape buffer between do_scrape and extract_content nodes
# not a clean pattern but required for node-to-node data passing
from typing import Any