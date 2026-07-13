import re

import httpx

from app.core.config import settings
from app.models.core import SearchHit

_SEARCH_TIMEOUT = 20.0

# Keywords that indicate we want live/real-time data — skip Wikipedia for these
_REALTIME_RE = re.compile(
    r"\b(flight|price|fare|weather|stock|news|score|rate|hotel|booking|ticket)\b",
    re.IGNORECASE,
)


def _engines_for(query: str) -> str:
    """Remove Wikipedia for real-time queries — it only has static encyclopedic content."""
    base = settings.searxng_engines
    if _REALTIME_RE.search(query):
        engines = [e.strip() for e in base.split(",") if e.strip() != "wikipedia"]
        return ",".join(engines) if engines else base
    return base


async def search(query: str, extra_engines: str | None = None) -> list[SearchHit]:
    """Query SearXNG, return up to settings.searxng_results ranked hits."""
    engines = extra_engines or _engines_for(query)
    params = {
        "q": query,
        "format": "json",
        "engines": engines,
        "language": "en",
        "safesearch": "0",
        "pageno": "1",
    }

    try:
        async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT) as client:
            resp = await client.get(f"{settings.searxng_url}/search", params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        print(f"[searxng] request error: {exc}")
        return []
    except Exception as exc:
        print(f"[searxng] unexpected error: {exc}")
        return []

    results = data.get("results", [])
    hits: list[SearchHit] = []

    for item in results[: settings.searxng_results]:
        url = item.get("url", "")
        title = item.get("title", "")
        content = item.get("content", "")
        engine = item.get("engine", "")
        score = float(item.get("score", 0.0))

        if url and title:
            hits.append(SearchHit(
                url=url,
                title=title,
                snippet=content[:300],
                engine=engine,
                score=score,
            ))

    return hits


async def multi_search(queries: list[str]) -> list[SearchHit]:
    """Run multiple queries and deduplicate results by URL."""
    import asyncio

    all_results = await asyncio.gather(*[search(q) for q in queries], return_exceptions=True)

    seen_urls: set[str] = set()
    merged: list[SearchHit] = []

    for result in all_results:
        if isinstance(result, Exception):
            continue
        for hit in result:
            if hit.url not in seen_urls:
                seen_urls.add(hit.url)
                merged.append(hit)

    # sort by score descending
    merged.sort(key=lambda h: h.score, reverse=True)
    return merged