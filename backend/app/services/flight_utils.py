"""
flight_utils.py — Extract flight parameters and build reliable URLs.

URL strategy:
  - GoIndiGo.in homepage (form automation in scraper.py)
  - Cleartrip direct search URL (reasonably bot-tolerant)
  - Air India direct booking (static enough to scrape)
  We AVOID: Skyscanner, MakeMyTrip, EaseMyTrip (Cloudflare),
             Rome2Rio (shows bus/train, not flights),
             Google/Bing SERP (bot-detected in Playwright).
"""
import re
from datetime import datetime
from urllib.parse import quote_plus

_AIRPORTS: dict[str, str] = {
    "mumbai": "BOM", "bombay": "BOM", "bom": "BOM",
    "delhi": "DEL", "new delhi": "DEL", "del": "DEL",
    "bangalore": "BLR", "bengaluru": "BLR", "blr": "BLR",
    "chennai": "MAA", "madras": "MAA", "maa": "MAA",
    "kolkata": "CCU", "calcutta": "CCU", "ccu": "CCU",
    "hyderabad": "HYD", "hyd": "HYD",
    "pune": "PNQ", "pnq": "PNQ",
    "goa": "GOI", "goi": "GOI",
    "ahmedabad": "AMD", "amd": "AMD",
    "kochi": "COK", "cochin": "COK", "ernakulam": "COK", "cok": "COK",
    "jaipur": "JAI", "jai": "JAI",
    "lucknow": "LKO", "lko": "LKO",
    "nagpur": "NAG", "nag": "NAG",
    "indore": "IDR", "idr": "IDR",
    "chandigarh": "IXC", "ixc": "IXC",
    "amritsar": "ATQ", "atq": "ATQ",
    "varanasi": "VNS", "vns": "VNS",
    "coimbatore": "CJB", "cjb": "CJB",
    "thiruvananthapuram": "TRV", "trivandrum": "TRV", "trv": "TRV",
    "bhubaneswar": "BBI", "bbi": "BBI",
    "patna": "PAT", "pat": "PAT",
    "srinagar": "SXR", "sxr": "SXR",
    "dubai": "DXB", "dxb": "DXB",
    "london": "LHR", "lhr": "LHR",
    "singapore": "SIN", "sin": "SIN",
    "new york": "JFK", "nyc": "JFK", "jfk": "JFK",
    "bangkok": "BKK", "bkk": "BKK",
    "frankfurt": "FRA", "fra": "FRA",
    "paris": "CDG", "cdg": "CDG",
    "toronto": "YYZ", "yyz": "YYZ",
    "sydney": "SYD", "syd": "SYD",
    "tokyo": "NRT", "nrt": "NRT",
}

_CODE_TO_CITY: dict[str, str] = {
    "BOM": "Mumbai", "DEL": "Delhi", "BLR": "Bangalore", "MAA": "Chennai",
    "CCU": "Kolkata", "HYD": "Hyderabad", "PNQ": "Pune", "GOI": "Goa",
    "AMD": "Ahmedabad", "COK": "Kochi", "JAI": "Jaipur", "LKO": "Lucknow",
    "NAG": "Nagpur", "IDR": "Indore", "IXC": "Chandigarh", "ATQ": "Amritsar",
    "VNS": "Varanasi", "CJB": "Coimbatore", "TRV": "Trivandrum",
    "BBI": "Bhubaneswar", "PAT": "Patna", "SXR": "Srinagar",
    "DXB": "Dubai", "LHR": "London", "SIN": "Singapore",
    "JFK": "New York", "BKK": "Bangkok", "FRA": "Frankfurt",
    "CDG": "Paris", "YYZ": "Toronto", "SYD": "Sydney", "NRT": "Tokyo",
}

_MONTH_NUMS: dict[str, int] = {
    "jan": 1, "january": 1, "feb": 2, "february": 2,
    "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_FLIGHT_RE = re.compile(
    r"\b(flight|flights?|ticket|tickets?|fare|fares?|airfare|fly|flying|plane|airline)\b",
    re.IGNORECASE,
)

# Sites we know work reliably with Playwright
_RELIABLE_FLIGHT_SITES = frozenset({"goindigo.in", "cleartrip.com", "spicejet.com", "airindia.in"})


def is_flight_query(query: str) -> bool:
    return bool(_FLIGHT_RE.search(query))


def is_indigo_url(url: str) -> bool:
    return "goindigo.in" in url.lower()


def is_flight_site(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
        return any(s in host for s in _RELIABLE_FLIGHT_SITES)
    except Exception:
        return False


def _extract_airports(query: str) -> tuple[str | None, str | None]:
    q = query.lower()
    seen_codes: set[str] = set()
    hits: list[tuple[int, str]] = []

    for name in sorted(_AIRPORTS, key=len, reverse=True):
        m = re.search(r"\b" + re.escape(name) + r"\b", q)
        if m:
            code = _AIRPORTS[name]
            if code not in seen_codes:
                seen_codes.add(code)
                hits.append((m.start(), code))

    hits.sort(key=lambda x: x[0])  # leftmost in text = origin
    codes = [c for _, c in hits]

    if len(codes) >= 2:
        return codes[0], codes[1]
    if len(codes) == 1:
        return codes[0], None
    return None, None


def _extract_date(query: str) -> dict | None:
    q = query.lower()
    year_now = datetime.now().year

    month_re = "(" + "|".join(_MONTH_NUMS) + ")"
    patterns = [
        re.compile(r"(\d{1,2})\s+" + month_re + r"(?:\s+(\d{4}))?", re.I),
        re.compile(month_re + r"\s+(\d{1,2})(?:[,\s]+(\d{4}))?", re.I),
        re.compile(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})"),
        re.compile(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})"),
    ]
    for i, pat in enumerate(patterns):
        m = pat.search(q)
        if not m:
            continue
        try:
            if i == 0:
                day, mon_s, yr_s = int(m.group(1)), m.group(2)[:3], m.group(3)
                month, year = _MONTH_NUMS[mon_s], int(yr_s) if yr_s else year_now
            elif i == 1:
                mon_s, day_s, yr_s = m.group(1)[:3], m.group(2), m.group(3)
                day, month, year = int(day_s), _MONTH_NUMS[mon_s], int(yr_s) if yr_s else year_now
            elif i == 2:
                day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            else:
                year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            dt = datetime(year, month, day)
            return {
                "yymmdd":   dt.strftime("%y%m%d"),
                "8digit":   dt.strftime("%Y%m%d"),
                "readable": dt.strftime("%B %d, %Y"),
                "short":    dt.strftime("%d %b %Y"),
                "dmy":      dt.strftime("%d/%m/%Y"),
                "iso":      dt.strftime("%Y-%m-%d"),
            }
        except (ValueError, KeyError):
            pass
    return None


def extract_flight_params(query: str) -> dict | None:
    if not is_flight_query(query):
        return None
    origin, destination = _extract_airports(query)
    if not (origin and destination):
        return None
    date = _extract_date(query)
    return {
        "origin":        origin,
        "destination":   destination,
        "origin_city":   _CODE_TO_CITY.get(origin, origin),
        "dest_city":     _CODE_TO_CITY.get(destination, destination),
        "date_yymmdd":   date["yymmdd"]   if date else None,
        "date_8digit":   date["8digit"]   if date else None,
        "date_readable": date["readable"] if date else None,
        "date_short":    date["short"]    if date else None,
        "date_dmy":      date["dmy"]      if date else None,
        "date_iso":      date["iso"]      if date else None,
    }


def build_flight_urls(params: dict) -> list[str]:
    """
    Return reliable flight search URLs.

    Priority:
      1. GoIndiGo homepage — scraper will do form automation to fill search
      2. Cleartrip direct search URL — reasonably bot-tolerant OTA
      3. SpiceJet direct search URL

    We deliberately exclude: Rome2Rio (multi-modal, shows bus/train),
    Skyscanner/MakeMyTrip/EaseMyTrip (Cloudflare-blocked),
    Google/Bing SERP (bot-detected even in headed mode).
    """
    o    = params["origin"]
    d    = params["destination"]
    urls: list[str] = []

    # 1. GoIndiGo — form automation happens inside scraper._automate_indigo()
    urls.append("https://www.goindigo.in")

    # 2. Cleartrip direct search result URL
    if params.get("date_dmy"):
        date_ct = params["date_dmy"]  # DD/MM/YYYY
        urls.append(
            f"https://www.cleartrip.com/flights/results"
            f"?adults=1&childs=0&infants=0&class=Economy"
            f"&depart_date={date_ct}&from={o}&to={d}"
        )

    # 3. SpiceJet
    if params.get("date_iso"):
        urls.append(
            f"https://book.spicejet.com/?from={o}&to={d}"
            f"&date={params['date_iso']}&adults=1&children=0&infants=0&triptype=O"
        )

    return urls


def build_flight_search_queries(params: dict) -> list[str]:
    """SearXNG queries that produce flight-price-rich snippets."""
    orig  = params.get("origin_city", params["origin"])
    dest  = params.get("dest_city",   params["destination"])
    date  = params.get("date_readable", "")
    short = params.get("date_short",    "")

    return [
        f"cheapest flight {orig} to {dest} {date} IndiGo SpiceJet Air India price fare",
        f"IndiGo SpiceJet {orig} {dest} {short} ticket price",
    ]
