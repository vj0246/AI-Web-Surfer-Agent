import threading
from collections import OrderedDict

from app.core.config import settings
from app.models.core import ChatMessage

# thread-safe ordered dict: session_id → [ChatMessage, ...]
_store: OrderedDict[str, list[ChatMessage]] = OrderedDict()
_lock = threading.Lock()


def get_history(session_id: str) -> list[ChatMessage]:
    with _lock:
        return list(_store.get(session_id, []))


def get_history_text(session_id: str) -> str:
    """Format last N turns as plain text for LLM prompts."""
    history = get_history(session_id)
    if not history:
        return "No previous conversation."
    lines = []
    for msg in history[-settings.session_max_turns :]:
        prefix = "User" if msg.role == "user" else "Assistant"
        lines.append(f"{prefix}: {msg.content[:400]}")
    return "\n".join(lines)


def append_turn(session_id: str, role: str, content: str, citations: list[dict] | None = None) -> None:
    with _lock:
        # evict oldest session if at capacity
        if session_id not in _store and len(_store) >= settings.session_max_sessions:
            _store.popitem(last=False)

        if session_id not in _store:
            _store[session_id] = []

        _store[session_id].append(
            ChatMessage(role=role, content=content, citations=citations or [])
        )

        # enforce sliding window
        if len(_store[session_id]) > settings.session_max_turns * 2:
            _store[session_id] = _store[session_id][-settings.session_max_turns * 2 :]


def clear_session(session_id: str) -> None:
    with _lock:
        _store.pop(session_id, None)


def list_sessions() -> list[str]:
    with _lock:
        return list(_store.keys())
