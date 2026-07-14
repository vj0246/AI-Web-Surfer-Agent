"""
chat.py v0.3 — SSE streams synthesizer tokens in real time via "token" events
"""
import asyncio
import json
import re
import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.pipeline.graph import pipeline
from app.pipeline.state import AgentState
from app.services.session_store import append_turn, get_history_text

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    query: str
    session_id: str = ""


_NODE_LABEL = {
    "analyze_query":   ("analyzing",    "Analyzing query..."),
    "check_cache":     ("cache_check",  "Checking semantic cache..."),
    "direct_answer":   ("direct",       "Answering directly..."),
    "plan":            ("planning",     "Planning research angles..."),
    "research":        ("researching",  "Researcher agent working..."),
    "critic":          ("critiquing",   "Reviewing coverage..."),
    "build_context":   ("building",     "Building synthesis context..."),
    "synthesize":      ("synthesizing", "Synthesizing final answer..."),
    "store_cache":     ("caching",      "Caching result..."),
}


def _node_payload(node: str, state: AgentState, update: dict | None = None) -> dict:
    """Build an SSE payload. `state` is the merged view; `update` is this node's own delta
    (used for per-researcher events, since researchers run in parallel)."""
    update = update or {}
    event_type, message = _NODE_LABEL.get(node, ("update", node))
    base = {"type": event_type, "node": node, "message": message}

    if node == "analyze_query":
        return {**base, "data": {
            "query_type": state.get("query_type", ""),
            "needs_web": state.get("needs_web", True),
            "sub_queries": state.get("sub_queries", []),
            "is_temporal": state.get("is_temporal", False),
        }}
    if node == "check_cache":
        return {**base, "data": {"cache_hit": state.get("cache_hit", False)}}
    if node == "plan":
        return {**base, "data": {
            "angles": state.get("plan_summary", []),
            "researchers": len(state.get("research_tasks", [])),
        }}
    if node == "research":
        # Prefer this researcher's own result (parallel-safe) over the merged view.
        results = update.get("researcher_results") or state.get("researcher_results", [])
        latest = results[-1] if results else {}
        return {**base, "data": {
            "sub_query": latest.get("sub_query", ""),
            "extracted": latest.get("extracted", 0),
            "high_relevance": latest.get("high_relevance", 0),
            "urls": latest.get("urls", []),
        }}
    if node == "critic":
        return {**base, "data": {
            "note": state.get("critic_note", ""),
            "done": state.get("critic_done", False),
            "round": state.get("critic_round", 0),
            "high_relevance": sum(
                1 for e in state.get("page_extracts", [])
                if (e.get("relevance_score", 0) if isinstance(e, dict) else 0) >= 5.0
            ),
        }}
    return {**base, "data": {}}


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """
    SSE endpoint. Pipeline events + real-time token streaming.

    Event types:
      analyzing | cache_check | planning | researching | critiquing |
      building | synthesizing | token | done | error
    """
    session_id = request.session_id or str(uuid.uuid4())
    query = request.query.strip()

    append_turn(session_id, "user", query)
    history_text = get_history_text(session_id)

    initial: AgentState = {
        "session_id": session_id,
        "query": query,
        "history_text": history_text,
        "query_type": "",
        "needs_web": True,
        "sub_queries": [],
        "is_temporal": False,
        "search_hits": [],
        "page_extracts": [],
        "errors": [],
        "cache_hit": False,
        "synthesis_context": "",
        "answer": "",
        "citations": [],
        "researcher_results": [],
        "research_tasks": [],
        "plan_summary": [],
        "critic_round": 0,
        "critic_done": False,
        "critic_note": "",
    }

    async def event_generator():
        final_state: AgentState = {**initial}
        full_answer = ""

        try:
            config = {"recursion_limit": 100}
            async for chunk in pipeline.astream(initial, config=config):
                # A super-step may complete several nodes at once (parallel researchers).
                for node_name, node_state in chunk.items():
                    if not isinstance(node_state, dict):
                        continue
                    final_state = {**final_state, **{k: v for k, v in node_state.items() if v is not None}}

                    # Synthesize node — stream the answer it already produced (single
                    # LLM call happens inside the node; here we just replay it as tokens).
                    if node_name == "synthesize" and not final_state.get("cache_hit"):
                        yield {"data": json.dumps({
                            "type": "synthesizing", "node": "synthesize",
                            "message": "Synthesizing final answer...", "data": {},
                        })}

                        answer = final_state.get("answer", "")
                        for tok in re.findall(r"\S+\s+|\S+|\s+", answer):
                            full_answer += tok
                            yield {"data": json.dumps({"type": "token", "node": "token", "token": tok})}
                            await asyncio.sleep(0.008)

                        final_state["answer"] = full_answer or answer
                        continue  # skip normal payload for synthesize

                    payload = _node_payload(node_name, final_state, node_state)
                    yield {"data": json.dumps(payload)}

            answer = final_state.get("answer", full_answer)
            citations = final_state.get("citations", [])

            append_turn(session_id, "assistant", answer, citations)

            yield {"data": json.dumps({
                "type": "done",
                "node": "__done__",
                "message": "Complete",
                "data": {
                    "session_id": session_id,
                    "answer": answer,
                    "citations": citations,
                    "cache_hit": final_state.get("cache_hit", False),
                    "errors": final_state.get("errors", []),
                },
            })}

        except Exception as exc:
            yield {"data": json.dumps({
                "type": "error", "node": "__error__",
                "message": str(exc), "data": {},
            })}

    return EventSourceResponse(event_generator())


@router.delete("/session/{session_id}")
def clear_session(session_id: str) -> dict:
    from app.services.session_store import clear_session as _clear
    _clear(session_id)
    return {"cleared": session_id}


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}