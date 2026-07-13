from urllib.parse import urlparse

from app.core.config import settings
from app.models.core import Citation, PageExtract


def build_context(
    page_extracts: list[dict],
    search_hits: list[dict] | None = None,
) -> tuple[str, list[Citation]]:
    """
    Build synthesis context from scraped page extracts + SearXNG snippets.

    Priority:
    1. Page extracts sorted by relevance (de-duped by domain)
    2. If remaining budget allows, append SearXNG search snippets — these
       often contain price/summary data that scraped pages miss (JS-heavy sites).
    """
    extracts = [PageExtract(**e) for e in page_extracts if e]
    extracts.sort(key=lambda x: x.relevance_score, reverse=True)

    seen_domains: set[str] = set()
    selected: list[PageExtract] = []

    for ex in extracts:
        try:
            domain = urlparse(ex.url).netloc
        except Exception:
            domain = ex.url
        if domain not in seen_domains:
            seen_domains.add(domain)
            selected.append(ex)
        if len(selected) >= settings.max_context_extracts:
            break

    citations: list[Citation] = []
    parts: list[str] = []
    total_chars = 0

    for i, ex in enumerate(selected):
        citation = Citation(
            index=i + 1,
            url=ex.url,
            title=ex.title,
            snippet=ex.relevant_text[:200],
        )
        citations.append(citation)

        section_lines = [f"[{i + 1}] {ex.title}", f"Source: {ex.url}"]
        if ex.key_facts:
            section_lines.append("Key facts:")
            section_lines.extend(f"  • {f}" for f in ex.key_facts)
        if ex.relevant_text:
            section_lines.append(ex.relevant_text)

        section = "\n".join(section_lines)

        if total_chars + len(section) > settings.max_context_chars:
            remaining = settings.max_context_chars - total_chars
            if remaining > 200:
                parts.append(section[:remaining] + "…")
            break

        parts.append(section)
        total_chars += len(section)

    # Supplement with SearXNG search snippets when there is budget remaining.
    # These snippets come directly from search engine result pages and often
    # contain price, date, and summary data not available in scraped HTML.
    snippet_budget = settings.max_context_chars - total_chars
    if search_hits and snippet_budget > 400:
        snippet_lines = ["[SEARCH SNIPPETS — direct from search engine results]"]
        added_snippet_domains: set[str] = set()

        for hit in search_hits:
            if isinstance(hit, dict):
                url = hit.get("url", "")
                title = hit.get("title", "")
                snippet = hit.get("snippet", "")
            else:
                url = getattr(hit, "url", "")
                title = getattr(hit, "title", "")
                snippet = getattr(hit, "snippet", "")

            if not snippet or not url:
                continue

            try:
                domain = urlparse(url).netloc
            except Exception:
                domain = url

            if domain in added_snippet_domains:
                continue
            added_snippet_domains.add(domain)

            line = f"• [{title}] ({domain}): {snippet[:250]}"
            if sum(len(l) for l in snippet_lines) + len(line) > snippet_budget:
                break
            snippet_lines.append(line)

        if len(snippet_lines) > 1:   # has at least one snippet
            parts.append("\n".join(snippet_lines))

    context = "\n\n---\n\n".join(parts)
    return context, citations
