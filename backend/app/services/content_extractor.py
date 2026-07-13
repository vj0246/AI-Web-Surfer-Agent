import json
import re

import ollama

from app.core.config import settings
from app.models.core import PageExtract

_EXTRACT_PROMPT = """You are extracting useful content from a web page to answer this question: "{query}"

IMPORTANT: If the question is about FLIGHTS (air travel), focus ONLY on:
  - Airline names (IndiGo, SpiceJet, Air India, Vistara, etc.)
  - Flight prices / fares in INR or USD
  - Departure and arrival times
  - Flight numbers and duration
  - Booking links for flights
  Ignore bus prices, train fares, taxi, car options even if the page shows them.

Extract:
1. relevant_text: the most relevant passage(s), max 1500 characters. Copy important text verbatim.
2. key_facts: 3-5 precise bullet points directly answering the question
3. relevance_score: float 0-10 (0=irrelevant, 5=somewhat related, 10=directly answers question)
4. title: page title or inferred topic

Return JSON only. No markdown:
{{"title": "...", "relevant_text": "...", "key_facts": ["...", "..."], "relevance_score": 7.5}}

Page content:
{content}"""


def _clean_html(html: str) -> str:
    """Strip scripts, styles, nav, footer; compress whitespace; truncate."""
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<nav[^>]*>.*?</nav>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<footer[^>]*>.*?</footer>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<header[^>]*>.*?</header>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    html = re.sub(r"<[^>]+>", " ", html)         # strip remaining tags
    html = re.sub(r"[ \t]+", " ", html)           # collapse spaces
    html = re.sub(r"\n{3,}", "\n\n", html)        # collapse blank lines
    return html[: settings.max_html_chars]


_JUNK_PATTERNS = re.compile(
    r"(search error|0 results|nothing found|page not found|"
    r"access denied|captcha|enable javascript|are you a robot|unusual traffic|"
    r"403 forbidden|service unavailable|too many requests)",
    re.IGNORECASE,
)
_JUNK_MIN_CHARS = 150  # cleaned text shorter than this is almost certainly empty/blocked


async def extract_page(html: str, url: str, query: str) -> PageExtract:
    """Extract relevant content from raw HTML using phi3:mini."""
    cleaned = _clean_html(html)

    # Junk-page short-circuit — error pages, bot-blocks, empty shells.
    # Skip the LLM call entirely; these never count as relevant extracts.
    if len(cleaned.strip()) < _JUNK_MIN_CHARS or _JUNK_PATTERNS.search(cleaned[:2000]):
        print(f"[extractor] {url} -> JUNK/BLOCKED (cleaned_len={len(cleaned.strip())}) score=0.0")
        return PageExtract(
            url=url,
            title="(junk/blocked page)",
            relevant_text="",
            key_facts=[],
            relevance_score=0.0,
        )

    prompt = _EXTRACT_PROMPT.format(query=query, content=cleaned)

    client = ollama.AsyncClient(host=settings.ollama_host)
    response = await client.generate(model=settings.planner_model, prompt=prompt)
    raw = response["response"].strip()

    raw = re.sub(r"^```(?:json)?", "", raw).rstrip("`").strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    raw = match.group() if match else raw

    try:
        data = json.loads(raw)
        extract = PageExtract(
            url=url,
            title=str(data.get("title", url)),
            relevant_text=str(data.get("relevant_text", ""))[:1500],
            key_facts=[str(f) for f in data.get("key_facts", [])[:5]],
            relevance_score=min(10.0, max(0.0, float(data.get("relevance_score", 5.0)))),
        )
        print(f"[extractor] {url} -> score={extract.relevance_score} title={extract.title!r}")
        return extract
    except (json.JSONDecodeError, ValueError):
        print(f"[extractor] {url} -> PARSE FAILED, raw={raw!r} -> fallback score=3.0")
        return PageExtract(
            url=url,
            title=url,
            relevant_text=cleaned[:500],
            key_facts=[],
            relevance_score=3.0,
        )


async def extract_pages_parallel(scrape_results: list[tuple[str, str]], query: str) -> list[PageExtract]:
    """Extract from multiple pages in parallel."""
    import asyncio

    tasks = [extract_page(html, url, query) for url, html in scrape_results]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    extracts = []
    for r in results:
        if isinstance(r, PageExtract):
            extracts.append(r)
        # silently skip extraction failures
    return extracts
