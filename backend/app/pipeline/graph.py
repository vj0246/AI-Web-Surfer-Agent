from langgraph.graph import END, StateGraph
from langgraph.types import Send

from app.pipeline.nodes import (
    node_analyze_query,
    node_build_context,
    node_check_cache,
    node_critic,
    node_direct_answer,
    node_plan,
    node_research,
    node_store_cache,
    node_synthesize,
)
from app.pipeline.state import AgentState


def _cache_router(state: AgentState) -> str:
    if state.get("cache_hit"):
        return "synthesize"
    if not state.get("needs_web"):
        return "direct_answer"
    return "plan"


def _dispatch_research(state: AgentState):
    """Fan out one researcher agent per planned task. No tasks -> straight to context."""
    tasks = state.get("research_tasks", [])
    if not tasks:
        return "build_context"
    session_id = state.get("session_id", "")
    query = state["query"]
    return [
        Send("research", {
            "query": query,
            "sub_query": t["sub_query"],
            "inject_flight": t.get("inject_flight", False),
            "session_id": session_id,
        })
        for t in tasks
    ]


def _critic_router(state: AgentState):
    """Either proceed to synthesis or dispatch a gap-filling researcher round."""
    if state.get("critic_done"):
        return "build_context"
    session_id = state.get("session_id", "")
    query = state["query"]
    return [
        Send("research", {
            "query": query,
            "sub_query": t["sub_query"],
            "inject_flight": t.get("inject_flight", False),
            "session_id": session_id,
        })
        for t in state.get("research_tasks", [])
    ]


def build_pipeline():
    graph = StateGraph(AgentState)

    graph.add_node("analyze_query", node_analyze_query)
    graph.add_node("check_cache", node_check_cache)
    graph.add_node("direct_answer", node_direct_answer)
    graph.add_node("plan", node_plan)
    graph.add_node("research", node_research)
    graph.add_node("critic", node_critic)
    graph.add_node("build_context", node_build_context)
    graph.add_node("synthesize", node_synthesize)
    graph.add_node("store_cache", node_store_cache)

    graph.set_entry_point("analyze_query")
    graph.add_edge("analyze_query", "check_cache")

    graph.add_conditional_edges(
        "check_cache",
        _cache_router,
        {"synthesize": "synthesize", "direct_answer": "direct_answer", "plan": "plan"},
    )

    # Planner fans out parallel researchers (or skips to context if no tasks).
    graph.add_conditional_edges("plan", _dispatch_research, ["research", "build_context"])

    # All researchers fan in at the critic.
    graph.add_edge("research", "critic")

    # Critic either proceeds or dispatches another bounded research round.
    graph.add_conditional_edges("critic", _critic_router, ["research", "build_context"])

    graph.add_edge("build_context", "synthesize")
    graph.add_edge("direct_answer", "store_cache")
    graph.add_edge("synthesize", "store_cache")
    graph.add_edge("store_cache", END)

    return graph.compile()


pipeline = build_pipeline()
