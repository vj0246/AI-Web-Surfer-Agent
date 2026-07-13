"""
scraper.py — Playwright scraper with live frame streaming.

Special behaviour for GoIndiGo.in:
  Runs automated form fill — types departure city, arrival city, date, clicks
  "Search Flights" — all while streaming screenshots to the browser panel.
  User sees Chrome on their desktop visiting IndiGo and filling in the form.

All sites: headed browser (headless=False), sequential (one window at a time),
domcontentloaded wait (avoids getting stuck on bot-detection pages).
"""
import asyncio
import base64
import concurrent.futures
import random
import sys

from app.core.config import settings
from app.services.browser_channel import put_frame

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

# Caps simultaneous headed Chrome windows when parallel researcher agents scrape at once.
# Created lazily so it binds to the running event loop.
_BROWSER_SEM: "asyncio.Semaphore | None" = None


def _browser_sem() -> asyncio.Semaphore:
    global _BROWSER_SEM
    if _BROWSER_SEM is None:
        _BROWSER_SEM = asyncio.Semaphore(settings.max_concurrent_browsers)
    return _BROWSER_SEM

# Travel/booking sites need extra JS rendering wait
_TRAVEL_DOMAINS = frozenset({
    "goindigo.in", "cleartrip.com", "spicejet.com", "airindia.in",
    "indigo.in", "book.goindigo.in",
})


def _is_travel_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
        return any(d in host for d in _TRAVEL_DOMAINS)
    except Exception:
        return False


def _is_indigo_url(url: str) -> bool:
    return "goindigo.in" in url.lower()


async def _capture_frame(page, session_id: str, url: str) -> None:
    try:
        shot = await page.screenshot(type="jpeg", quality=60, full_page=False)
        put_frame(session_id, {
            "type": "frame",
            "frame": base64.b64encode(shot).decode(),
            "url": url,
        })
    except Exception:
        pass


async def _stream_frames(page, session_id: str, url: str, count: int, interval: float) -> None:
    for _ in range(count):
        await _capture_frame(page, session_id, url)
        await asyncio.sleep(interval)


# ─────────────────────────────────────────────────────────────────────────────
# GoIndiGo form automation
# ─────────────────────────────────────────────────────────────────────────────

async def _dismiss_popup(page) -> None:
    """Close cookie consent / promo popups that block the search form."""
    popup_selectors = [
        "button.close", "[aria-label='Close']", ".modal-close",
        "button:has-text('Accept')", "button:has-text('OK')",
        "button:has-text('Close')", ".cookie-consent button",
        "[class*='popup'] button", "[class*='modal'] button.btn-close",
    ]
    for sel in popup_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1000):
                await btn.click(timeout=1000)
                await page.wait_for_timeout(500)
                break
        except Exception:
            pass


async def _fill_airport(page, field_selectors: list[str], city_name: str, iata: str) -> bool:
    """Try each selector until one works; type city name and pick autocomplete."""
    for sel in field_selectors:
        try:
            field = page.locator(sel).first
            if not await field.is_visible(timeout=2000):
                continue
            await field.click(timeout=2000)
            await page.wait_for_timeout(400)
            await field.fill("")
            await field.type(city_name, delay=80)
            await page.wait_for_timeout(1200)

            # Pick first autocomplete option
            autocomplete_selectors = [
                f"[role='option']:has-text('{iata}')",
                f"[role='option']:has-text('{city_name}')",
                f"li:has-text('{iata}')",
                f"li:has-text('{city_name}')",
                "[role='listbox'] [role='option']:first-child",
                ".autocomplete__menu-item:first-child",
                "[class*='suggestion']:first-child",
                "[class*='dropdown'] li:first-child",
            ]
            picked = False
            for ac_sel in autocomplete_selectors:
                try:
                    opt = page.locator(ac_sel).first
                    if await opt.is_visible(timeout=1500):
                        await opt.click(timeout=1500)
                        picked = True
                        break
                except Exception:
                    pass
            if not picked:
                # Fallback: arrow-down + Enter
                await page.keyboard.press("ArrowDown")
                await page.wait_for_timeout(300)
                await page.keyboard.press("Enter")
            return True
        except Exception:
            continue
    return False


async def _automate_indigo(page, flight_params: dict, session_id: str) -> None:
    """
    Fill GoIndiGo search form: origin → destination → date → Search.
    Streams screenshots throughout so the user can watch it happen.
    """
    url = "https://www.goindigo.in"
    origin      = flight_params.get("origin", "BOM")
    dest        = flight_params.get("destination", "DEL")
    origin_city = flight_params.get("origin_city", "Mumbai")
    dest_city   = flight_params.get("dest_city",   "Delhi")
    date_iso    = flight_params.get("date_iso")      # YYYY-MM-DD
    date_dmy    = flight_params.get("date_dmy")      # DD/MM/YYYY
    date_short  = flight_params.get("date_short", "")  # 30 Jun 2026

    if session_id:
        await _stream_frames(page, session_id, url, count=3, interval=0.6)

    # Dismiss any popup
    await _dismiss_popup(page)

    # ── Try clicking "One Way" tab ───────────────────────────────────────
    one_way_selectors = [
        "label[for='one-way']", "input[value='O'] + label",
        "button:has-text('One Way')", "[data-trip-type='O']",
        "[class*='oneway']", "li:has-text('One Way')",
    ]
    for sel in one_way_selectors:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=1000):
                await el.click(timeout=1000)
                await page.wait_for_timeout(300)
                break
        except Exception:
            pass

    if session_id:
        await _stream_frames(page, session_id, url, count=2, interval=0.5)

    # ── Fill origin ──────────────────────────────────────────────────────
    origin_selectors = [
        "[id*='origin'] input", "[id*='from'] input",
        "[placeholder*='From']", "[placeholder*='Departure City']",
        "[placeholder*='Origin']", "[aria-label*='From']",
        "[class*='origin'] input", "[class*='from'] input",
        "[name='origin']", "[name='from']",
        "input[id*='src']", "[data-field='origin'] input",
    ]
    filled_origin = await _fill_airport(page, origin_selectors, origin_city, origin)
    if session_id:
        await _stream_frames(page, session_id, url, count=2, interval=0.5)

    # ── Fill destination ─────────────────────────────────────────────────
    await page.wait_for_timeout(600)
    dest_selectors = [
        "[id*='destination'] input", "[id*='to'] input",
        "[placeholder*='To']", "[placeholder*='Arrival City']",
        "[placeholder*='Destination']", "[aria-label*='To']",
        "[class*='destination'] input", "[class*='to-city'] input",
        "[name='destination']", "[name='to']",
        "input[id*='dst']", "[data-field='destination'] input",
    ]
    filled_dest = await _fill_airport(page, dest_selectors, dest_city, dest)
    if session_id:
        await _stream_frames(page, session_id, url, count=2, interval=0.5)

    # ── Set date ─────────────────────────────────────────────────────────
    if date_iso or date_dmy:
        await page.wait_for_timeout(500)
        date_selectors = [
            "input[type='date']",
            "[class*='datepicker'] input", "[class*='date-input'] input",
            "[placeholder*='Date']", "[placeholder*='Departure Date']",
            "[aria-label*='Date']", "[id*='date'] input",
            "[name='date']", "[name='depart']",
        ]
        for sel in date_selectors:
            try:
                date_field = page.locator(sel).first
                if await date_field.is_visible(timeout=1500):
                    await date_field.click(timeout=1500)
                    await page.wait_for_timeout(400)
                    # Try ISO format first (YYYY-MM-DD), then DD/MM/YYYY
                    val_to_try = date_iso or date_dmy or ""
                    try:
                        await date_field.fill(val_to_try)
                        await page.wait_for_timeout(500)
                    except Exception:
                        pass

                    # If a calendar picker opened, try navigating to the right date
                    if date_short:
                        try:
                            day_cell = page.locator(
                                f"[aria-label*='{date_short}'], td:has-text('{date_short[:2].lstrip('0')}'):not([class*='disabled'])"
                            ).first
                            if await day_cell.is_visible(timeout=1000):
                                await day_cell.click(timeout=1000)
                        except Exception:
                            pass
                    break
            except Exception:
                continue

    if session_id:
        await _stream_frames(page, session_id, url, count=2, interval=0.5)

    # ── Click Search ─────────────────────────────────────────────────────
    await page.wait_for_timeout(500)
    search_selectors = [
        "button[type='submit']",
        "button:has-text('Search Flights')", "button:has-text('Search flights')",
        "button:has-text('Search')", "button:has-text('Find Flights')",
        "[class*='search-btn']", "[class*='searchBtn']",
        "input[type='submit']",
    ]
    clicked_search = False
    for sel in search_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500):
                await btn.click(timeout=2000)
                clicked_search = True
                break
        except Exception:
            continue

    if session_id:
        await _stream_frames(page, session_id, url, count=2, interval=0.6)

    # Wait for results to load
    if clicked_search:
        await page.wait_for_timeout(5000)
        if session_id:
            await _stream_frames(page, session_id, url, count=5, interval=0.7)
        # Scroll to reveal flight list
        await page.evaluate("window.scrollBy(0, 500)")
        await page.wait_for_timeout(1000)
        if session_id:
            await _stream_frames(page, session_id, url, count=4, interval=0.6)
    else:
        # Form fill failed — still show the page
        await page.wait_for_timeout(1500)
        await page.evaluate("window.scrollBy(0, 300)")
        if session_id:
            await _stream_frames(page, session_id, url, count=3, interval=0.5)

    print(f"[indigo] filled_origin={filled_origin} filled_dest={filled_dest} clicked_search={clicked_search}")


# ─────────────────────────────────────────────────────────────────────────────
# Core scrape function
# ─────────────────────────────────────────────────────────────────────────────

def _scrape_sync(
    url: str,
    session_id: str = "",
    flight_params: dict | None = None,
) -> tuple[str, str] | None:
    """
    Playwright scrape in its own event loop (thread-safe).
    For GoIndiGo URLs: runs form automation via _automate_indigo().
    Returns (html, final_screenshot_b64) or None on failure.
    """
    travel  = _is_travel_url(url)
    indigo  = _is_indigo_url(url)

    async def _run():
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=settings.scraper_headless,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                context = await browser.new_context(
                    user_agent=random.choice(_USER_AGENTS),
                    viewport={"width": 1280, "height": 800},
                    locale="en-US",
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    },
                )
                await context.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
                )
                page = await context.new_page()

                # Signal navigation start
                if session_id:
                    put_frame(session_id, {"type": "url", "url": url})

                await page.wait_for_timeout(random.randint(400, 900))

                # ── Navigate ─────────────────────────────────────────────
                try:
                    await page.goto(
                        url,
                        timeout=settings.scraper_timeout_ms,
                        wait_until="domcontentloaded",
                    )
                except PWTimeout:
                    print(f"[scraper] nav timeout {url} — using what loaded")
                except Exception as exc:
                    print(f"[scraper] nav error {url}: {exc}")
                    if session_id:
                        put_frame(session_id, {"type": "error", "url": url, "message": str(exc)})
                    await browser.close()
                    return None

                # ── IndiGo form automation ───────────────────────────────
                if indigo and flight_params:
                    await page.wait_for_timeout(2500)  # let homepage fully render
                    await _automate_indigo(page, flight_params, session_id)
                else:
                    # ── Generic page handling ────────────────────────────
                    js_wait = 3000 if travel else 800
                    await page.wait_for_timeout(js_wait)

                    if session_id:
                        await _stream_frames(page, session_id, url, count=4, interval=0.45)

                    await page.evaluate("window.scrollBy(0, 400)")
                    await page.wait_for_timeout(700 if travel else 250)
                    if session_id:
                        await _stream_frames(page, session_id, url, count=3, interval=0.4)

                    await page.evaluate("window.scrollBy(0, 500)")
                    await page.wait_for_timeout(500 if travel else 200)
                    if session_id:
                        await _stream_frames(page, session_id, url, count=3, interval=0.35)

                    # Scroll back to top
                    await page.evaluate("window.scrollTo(0, 0)")
                    await page.wait_for_timeout(300)
                    if session_id:
                        await _stream_frames(page, session_id, url, count=2, interval=0.3)

                html = await page.content()

                final_b64 = ""
                try:
                    shot = await page.screenshot(type="jpeg", quality=60, full_page=False)
                    final_b64 = base64.b64encode(shot).decode()
                except Exception:
                    pass

                await browser.close()
                return html, final_b64

        except Exception as exc:
            print(f"[scraper] failed {url}: {exc}")
            if session_id:
                put_frame(session_id, {"type": "error", "url": url, "message": str(exc)})
            return None

    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


async def scrape_all(
    urls: list[str],
    session_id: str = "",
    flight_params: dict | None = None,
) -> list[tuple[str, str, str]]:
    """
    Sequential scraping (max_workers=1) — one Chrome window at a time.
    Returns list of (url, html, final_screenshot_b64).
    """
    loop = asyncio.get_event_loop()

    def _scrape_with_session(url: str) -> tuple[str, str] | None:
        return _scrape_sync(url, session_id, flight_params)

    # Bound concurrent browsers across parallel researcher agents.
    async with _browser_sem():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            futures = [loop.run_in_executor(pool, _scrape_with_session, url) for url in urls]
            results = await asyncio.gather(*futures, return_exceptions=True)

    if session_id:
        put_frame(session_id, {"type": "idle"})

    out = []
    for url, result in zip(urls, results):
        if isinstance(result, Exception):
            print(f"[scraper] exception for {url}: {result}")
            continue
        if isinstance(result, tuple) and result and result[0]:
            html, screenshot_b64 = result
            out.append((url, html, screenshot_b64))
    return out
