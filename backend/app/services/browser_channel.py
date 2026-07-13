"""
browser_channel.py — thread-safe frame queue per session.

The scraper runs in worker threads with their own event loops.
This module bridges those threads to the main async WebSocket handler
using a plain threading.Queue (safe from any thread/loop).
"""
import queue
import threading

_channels: dict[str, queue.Queue] = {}
_lock = threading.Lock()


def _get_q(session_id: str) -> queue.Queue:
    with _lock:
        if session_id not in _channels:
            _channels[session_id] = queue.Queue(maxsize=40)
        return _channels[session_id]


def put_frame(session_id: str, msg: dict) -> None:
    """Called from scraper threads. Drops oldest frame if queue is full."""
    if not session_id:
        return
    q = _get_q(session_id)
    try:
        q.put_nowait(msg)
    except queue.Full:
        try:
            q.get_nowait()          # discard oldest frame to make room
        except queue.Empty:
            pass
        try:
            q.put_nowait(msg)
        except queue.Full:
            pass


def poll_frame(session_id: str) -> dict | None:
    """Called from the async WebSocket handler (main loop). Non-blocking."""
    q = _channels.get(session_id)
    if q is None:
        return None
    try:
        return q.get_nowait()
    except queue.Empty:
        return None


def cleanup(session_id: str) -> None:
    with _lock:
        _channels.pop(session_id, None)
