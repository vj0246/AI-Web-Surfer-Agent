from app.services.context_builder import build_context

HIT_A = {"url": "https://a.com/x", "title": "Alpha", "snippet": "alpha snippet content"}
HIT_B = {"url": "https://b.com/y", "title": "Beta", "snippet": "beta snippet content"}


def _extract(url, text="real text", facts=("f1",), score=9.0, title="T"):
    return {"url": url, "title": title, "relevant_text": text, "key_facts": list(facts), "relevance_score": score}


def test_snippet_fallback_when_no_extracts():
    # Fully blocked scrape -> SearXNG snippets become citeable sources.
    ctx, cites = build_context([], search_hits=[HIT_A, HIT_B])
    assert len(cites) == 2
    assert cites[0].url == "https://a.com/x"
    assert "[1]" in ctx and "alpha snippet content" in ctx


def test_extract_preferred_over_hit():
    ctx, cites = build_context([_extract("https://c.com")], search_hits=[HIT_A])
    assert cites[0].url == "https://c.com"


def test_junk_extract_skipped_hit_promoted():
    junk = _extract("https://blocked.com", text="", facts=(), score=0.0, title="(junk/blocked page)")
    ctx, cites = build_context([junk], search_hits=[HIT_A])
    assert cites and cites[0].url == "https://a.com/x"


def test_empty_everything():
    ctx, cites = build_context([], search_hits=[])
    assert cites == []
    assert ctx == ""


def test_domain_dedupe():
    ext = [_extract("https://x.com/1", score=9.0), _extract("https://x.com/2", score=8.0)]
    ctx, cites = build_context(ext, search_hits=[])
    assert len(cites) == 1  # same domain collapses to one


def test_relevance_ordering():
    ext = [_extract("https://low.com", score=6.0, title="LOW"),
           _extract("https://high.com", score=9.5, title="HIGH")]
    ctx, cites = build_context(ext, search_hits=[])
    assert cites[0].url == "https://high.com"  # highest relevance first
