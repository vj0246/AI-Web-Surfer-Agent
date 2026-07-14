from app.api.chat import _merge_state


def test_reducer_keys_accumulate():
    # Parallel researchers each emit a delta; reducer channels must accumulate.
    s = {"researcher_results": [{"a": 1}], "page_extracts": [1], "search_hits": [], "answer": "old"}
    out = _merge_state(s, {"researcher_results": [{"b": 2}], "page_extracts": [2], "answer": "new"})
    assert out["researcher_results"] == [{"a": 1}, {"b": 2}]
    assert out["page_extracts"] == [1, 2]
    assert out["answer"] == "new"  # non-reducer scalar overwrites


def test_none_values_skipped():
    out = _merge_state({"answer": "keep"}, {"answer": None})
    assert out["answer"] == "keep"


def test_non_reducer_list_overwrites():
    # citations is not a reducer channel -> latest build_context value wins.
    out = _merge_state({"citations": [1, 2]}, {"citations": [3]})
    assert out["citations"] == [3]
