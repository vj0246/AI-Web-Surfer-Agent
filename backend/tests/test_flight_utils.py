from app.services.flight_utils import (
    build_flight_search_queries,
    build_flight_urls,
    extract_flight_params,
    is_flight_query,
)


def test_is_flight_query():
    assert is_flight_query("cheapest flight mumbai to delhi")
    assert is_flight_query("air india ticket price")
    assert not is_flight_query("what is a graph database")


def test_extract_params_basic():
    p = extract_flight_params("cheapest flight Mumbai to Delhi on 30 July 2026")
    assert p["origin"] == "BOM"
    assert p["destination"] == "DEL"
    assert p["origin_city"] == "Mumbai"
    assert p["dest_city"] == "Delhi"
    assert p["date_iso"] == "2026-07-30"
    assert p["date_dmy"] == "30/07/2026"


def test_extract_params_origin_order():
    # leftmost city in the text is the origin
    p = extract_flight_params("flight from Delhi to Bangalore")
    assert p["origin"] == "DEL"
    assert p["destination"] == "BLR"


def test_extract_params_requires_two_airports():
    assert extract_flight_params("flight prices today") is None
    assert extract_flight_params("flight from Mumbai") is None


def test_extract_params_not_a_flight():
    assert extract_flight_params("weather in Mumbai and Delhi") is None


def test_build_flight_urls_includes_indigo():
    p = extract_flight_params("flight Mumbai to Delhi on 30 July 2026")
    urls = build_flight_urls(p)
    assert any("goindigo.in" in u for u in urls)


def test_build_flight_search_queries():
    p = extract_flight_params("flight Mumbai to Delhi on 30 July 2026")
    qs = build_flight_search_queries(p)
    assert len(qs) >= 1
    assert all("Mumbai" in q and "Delhi" in q for q in qs)
