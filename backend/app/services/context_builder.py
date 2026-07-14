from urllib.parse import urlparse

from app.core.config import settings
from app.models.core import Citation, PageExtract


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url


def _hit_field(hit, name: str) -> str:
    if isinstance(hit, dict):
        return hit.get(name, "")
    return getattr(hit, name, "")


def build_context(
    page_extracts: list[dict],
    search_hits: list[dict] | None = None,
) -> tuple[str, list[Citation]]:
    """
    Build the synthesis context + numbered citations.

    Sources are chosen best-first, one per domain, up to max_context_extracts:
      1. Scraped page extracts that actually have content (relevant_text / key_facts).
      2. If scraping came back thin (bot-blocked pages, empty extracts), SearXNG hit
         snippets are promoted to first-class citeable sources so the answer is still
         grounded and cited instead of falling back to an uncited direct answer.

    Any remaining SearXNG snippets are appended as an extra un-numbered block when
    there is char budget left (useful for price/summary data JS-heavy pages miss).
    """
    extracts = [PageExtract(**e) for e in page_extracts if e]
    extracts = [e for e in extracts if e.relevant_text.strip() or e.key_facts]
    extracts.sort(key=lambda x: x.relevance_score, reverse=True)

    sources: list[dict] = []
    seen_domains: set[str] = set()

    for e in extracts:
        d = _domain(e.url)
        if d in seen_domains:
            continue
        seen_domains.add(d)
        sources.append({"url": e.url, "title": e.title, "text": e.relevant_text, "facts": e.key_facts})
        if len(sources) >= settings.max_context_extracts:
            break

    # Fallback: fill remaining slots with SearXNG snippets as citeable sources.
    used_hit_urls: set[str] = set()
    if len(sources) < settings.max_context_extracts and search_hits:
        for hit in search_hits:
            if len(sources) >= settings.max_context_extracts:
                break
            url = _hit_field(hit, "url")
            snippet = _hit_field(hit, "snippet")
            if not url or not snippet:
                continue
            d = _domain(url)
            if d in seen_domains:
                continue
            seen_domains.add(d)
            used_hit_urls.add(url)
            sources.append({"url": url, "title": _hit_field(hit, "title"), "text": snippet, "facts": []})

    citations: list[Citation] = []
    parts: list[str] = []
    total_chars = 0

    for i, s in enumerate(sources):
        idx = i + 1
        citations.append(Citation(index=idx, url=s["url"], title=s["title"], snippet=s["text"][:200]))

        lines = [f"[{idx}] {s['title']}", f"Source: {s['url']}"]
        if s["facts"]:
            lines.append("Key facts:")
            lines.extend(f"  • {f}" for f in s["facts"])
        if s["text"]:
            lines.append(s["text"])
        section = "\n".join(lines)

        if total_chars + len(section) > settings.max_context_chars:
            remaining = settings.max_context_chars - total_chars
            if remaining > 200:
                parts.append(section[:remaining] + "…")
            break
        parts.append(section)
        total_chars += len(section)

    # Extra snippets (not already used) as bonus context if budget remains.
    snippet_budget = settings.max_context_chars - total_chars
    if search_hits and snippet_budget > 400:
        snippet_lines = ["[ADDITIONAL SEARCH SNIPPETS]"]
        added: set[str] = set(seen_domains)
        for hit in search_hits:
            url = _hit_field(hit, "url")
            snippet = _hit_field(hit, "snippet")
            if not url or not snippet or url in used_hit_urls:
                continue
            d = _domain(url)
            if d in added:
                continue
            added.add(d)
            line = f"• [{_hit_field(hit, 'title')}] ({d}): {snippet[:250]}"
            if sum(len(l) for l in snippet_lines) + len(line) > snippet_budget:
                break
            snippet_lines.append(line)
        if len(snippet_lines) > 1:
            parts.append("\n".join(snippet_lines))

    return "\n\n---\n\n".join(parts), citations
