"""
browser_ws.py — WebSocket endpoint that forwards live browser frames to the frontend.
Polls the per-session frame queue at ~50 ms intervals when idle, instantly when frames arrive.
"""
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.browser_channel import cleanup, poll_frame

router = APIRouter()


@router.websocket("/ws/browser/{session_id}")
async def browser_stream(websocket: WebSocket, session_id: str):
    await websocket.accept()
    try:
        while True:
            msg = poll_frame(session_id)
            if msg is not None:
                await websocket.send_json(msg)
            else:
                await asyncio.sleep(0.04)   # poll every 40 ms when idle
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        cleanup(session_id)
