"""
synthesizer.py v0.3:
  - token-by-token streaming via ollama stream=True
  - yields str chunks via async generator
  - caller (chat.py SSE) forwards each token to frontend
"""
from collections.abc import AsyncGenerator

import ollama

from app.core.config import settings

_SYNTH_PROMPT = """You are a precise research assistant. Answer using the provided sources.

Conversation history:
{history_text}

Question: {query}

Sources (cite inline as [N]):
{context}

Rules:
- Cite every fact with [N] inline — never state facts without citing them
- If the question is about FLIGHTS specifically: report ONLY air travel options — airlines, prices,
  departure/arrival times, flight numbers, duration. IGNORE bus, train, car options even if the
  sources mention them.
- If sources contain actual prices or flight details → state them clearly
- If sources only have partial data (e.g. price ranges) → share what's available and note which
  airline website to check for booking (e.g. goindigo.in, spicejet.com, airindia.in)
- For comparisons: use a plain-text table
- Do NOT say "I cannot provide real-time data" if the sources DO have relevant information
- Do NOT invent facts not in the sources
- End with a one-sentence TL;DR"""

_DIRECT_PROMPT = """You are a knowledgeable assistant in a multi-turn conversation.

History:
{history_text}

Question: {query}

Answer concisely. No web search needed."""


async def stream_synthesis(
    query: str,
    context: str,
    history_text: str,
) -> AsyncGenerator[str, None]:
    """Stream final answer token by token."""
    prompt = _SYNTH_PROMPT.format(
        history_text=history_text or "None",
        query=query,
        context=context,
    )
    client = ollama.AsyncClient(host=settings.ollama_host)
    async for chunk in await client.generate(
        model=settings.synthesizer_model,
        prompt=prompt,
        stream=True,
    ):
        token = chunk.get("response", "")
        if token:
            yield token


async def stream_direct(
    query: str,
    history_text: str,
) -> AsyncGenerator[str, None]:
    """Stream direct answer (no web) token by token."""
    prompt = _DIRECT_PROMPT.format(
        history_text=history_text or "None",
        query=query,
    )
    client = ollama.AsyncClient(host=settings.ollama_host)
    async for chunk in await client.generate(
        model=settings.synthesizer_model,
        prompt=prompt,
        stream=True,
    ):
        token = chunk.get("response", "")
        if token:
            yield token


async def synthesize_full(
    query: str,
    context: str,
    history_text: str,
) -> str:
    """Non-streaming version for cache storage."""
    return "".join([t async for t in stream_synthesis(query, context, history_text)])


async def synthesize_direct_full(query: str, history_text: str) -> str:
    return "".join([t async for t in stream_direct(query, history_text)])