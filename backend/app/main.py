import asyncio
import sys

# Windows fix: Playwright needs ProactorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import browser_ws, chat
from app.core.config import settings

app = FastAPI(title="Web Agent API", version="0.2.0", description="Local ReAct web agent — no cloud APIs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(chat.router)
app.include_router(browser_ws.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "web-agent-backend", "version": "0.2.0"}