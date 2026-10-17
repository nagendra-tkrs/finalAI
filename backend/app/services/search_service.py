import os
import re
import time
import asyncio
import logging
from urllib.parse import urlparse, parse_qs, unquote
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("email_discovery.search")

# Configuration defaults
SEARCH_TIMEOUT_SECONDS = float(os.getenv("SEARCH_TIMEOUT_SECONDS", "10.0"))
SEARCH_MAX_RETRIES = int(os.getenv("SEARCH_MAX_RETRIES", "2"))
SEARCH_RETRY_DELAY_SECONDS = float(os.getenv("SEARCH_RETRY_DELAY_SECONDS", "1.0"))
SEARCH_CACHE_TTL = 1800.0  # 30 minutes in-memory cache

_circuit_broken_until = 0.0
_search_cache = {}  # query -> (timestamp, result_dict)

def is_circuit_open() -> bool:
    global _circuit_broken_until
    return time.time() < _circuit_broken_until

def trip_circuit(cooldown_sec: float = 45.0):
    global _circuit_broken_until
    _circuit_broken_until = time.time() + cooldown_sec
    logger.warning(f"[SearchCircuit] Search circuit breaker tripped for {cooldown_sec}s")

def reset_circuit():
    global _circuit_broken_until
    _circuit_broken_until = 0.0

def decode_redirect_url(raw_url: str = "") -> str:
    """Decodes DuckDuckGo redirect URLs (//duckduckgo.com/l/?uddg=...) to real target URLs."""
    if not raw_url:
        return ""
    try:
        if "uddg=" in raw_url:
            parsed = urlparse(raw_url)
            query_params = parse_qs(parsed.query)
            uddg = query_params.get("uddg")
            if uddg:
                return unquote(uddg[0])
        if raw_url.startswith("//"):
            raw_url = "https:" + raw_url
        return raw_url if raw_url.startswith("http") else ""
    except Exception:
        return raw_url

def extract_domain(url: str = "") -> str:
    try:
        hostname = urlparse(url).hostname or ""
        return re.sub(r"^www\.", "", hostname, flags=re.IGNORECASE).lower()
    except Exception:
        return ""

def is_challenge_or_blocked_page(html_text: str = "") -> bool:
    if not html_text:
        return False
    lower = html_text[:15000].lower()
    markers = [
        "anomaly", "unusual traffic", "captcha", "are you a robot",
        "verify you are human", "attention required", "ddg_anomaly",
        "access denied", "403 forbidden"
    ]
    return any(m in lower for m in markers)

def parse_duckduckgo_html(html_text: str) -> list[dict]:
    results = []
    if not html_text:
        return results
    seen = set()
    try:
        soup = BeautifulSoup(html_text, "html.parser")
        bodies = soup.find_all("div", class_=re.compile(r"result__body"))
        for body in bodies:
            a_title = body.find("a", class_=re.compile(r"result__a"))
            a_snippet = body.find("a", class_=re.compile(r"result__snippet")) or body.find("div", class_=re.compile(r"result__snippet"))

            title = a_title.get_text().strip() if a_title else ""
            raw_href = a_title.get("href", "") if a_title else ""
            url = decode_redirect_url(raw_href)
            snippet = a_snippet.get_text().strip() if a_snippet else ""

            if not title or not url or url in seen:
                continue
            seen.add(url)
            results.append({
                "title": title,
                "url": url,
                "snippet": snippet,
                "domain": extract_domain(url),
                "position": len(results) + 1
            })
    except Exception as e:
        logger.warning(f"Error parsing DuckDuckGo HTML: {e}")
    return results

async def search_public_web(query: str, max_results: int = 5, timeout: float = None, options: dict = None) -> dict:
    """
    Central authoritative search interface for public web search.
    Returns:
        {
            "query": str,
            "results": list[dict], # [{"title", "url", "snippet", "domain", "position"}]
            "status": "OK" | "NO_RESULTS" | "SEARCH_TIMEOUT" | "SEARCH_UNAVAILABLE",
            "error": str or None,
            "provider": "duckduckgo"
        }
    """
    if options is None:
        options = {}

    clean_query = query.strip()
    if not clean_query:
        return {
            "query": query,
            "results": [],
            "status": "NO_RESULTS",
            "error": "EMPTY_QUERY",
            "provider": "duckduckgo"
        }

    # Check cache
    now = time.time()
    if clean_query in _search_cache:
        cached_time, cached_res = _search_cache[clean_query]
        if now - cached_time < SEARCH_CACHE_TTL:
            return cached_res

    if is_circuit_open():
        return {
            "query": clean_query,
            "results": [],
            "status": "SEARCH_UNAVAILABLE",
            "error": "Circuit breaker is active due to recent rate limits",
            "provider": "duckduckgo"
        }

    req_timeout = timeout or SEARCH_TIMEOUT_SECONDS
    max_retries = options.get("max_retries", SEARCH_MAX_RETRIES)

    # Attempt 1: Try duckduckgo_search / ddgs library if installed
    try:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            from ddgs import DDGS

        for attempt in range(max_retries + 1):
            try:
                loop = asyncio.get_event_loop()
                def _do_ddgs():
                    with DDGS(timeout=req_timeout) as ddgs:
                        return list(ddgs.text(clean_query, max_results=max_results))

                raw_items = await loop.run_in_executor(None, _do_ddgs)
                if raw_items:
                    results = []
                    for idx, item in enumerate(raw_items, 1):
                        href = decode_redirect_url(item.get("href") or item.get("url") or "")
                        title = item.get("title") or ""
                        snippet = item.get("body") or item.get("snippet") or ""
                        if href:
                            results.append({
                                "title": title,
                                "url": href,
                                "snippet": snippet,
                                "domain": extract_domain(href),
                                "position": idx
                            })
                    if results:
                        out = {
                            "query": clean_query,
                            "results": results[:max_results],
                            "status": "OK",
                            "error": None,
                            "provider": "duckduckgo"
                        }
                        _search_cache[clean_query] = (now, out)
                        return out
                break  # If returned empty list, try HTTP fallback
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "ratelimit" in err_str or "anomaly" in err_str:
                    trip_circuit(45.0)
                    return {
                        "query": clean_query,
                        "results": [],
                        "status": "SEARCH_UNAVAILABLE",
                        "error": f"DuckDuckGo rate limit or block: {e}",
                        "provider": "duckduckgo"
                    }
                if attempt < max_retries and ("timeout" in err_str or "timed out" in err_str):
                    await asyncio.sleep(SEARCH_RETRY_DELAY_SECONDS * (attempt + 1))
                    continue
                break
    except Exception as e:
        logger.debug(f"DDGS library search failed: {e}")

    # Attempt 2: Direct HTTP scrape fallback with proper browser headers
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache"
    }

    last_error = ""
    last_status = "SEARCH_UNAVAILABLE"

    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=req_timeout, follow_redirects=True) as client:
                res = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": clean_query},
                    headers=headers
                )
                if res.status_code in (202, 403, 429):
                    trip_circuit(60.0)
                    last_status = "SEARCH_UNAVAILABLE"
                    last_error = f"DuckDuckGo returned HTTP {res.status_code} challenge"
                    break
                if res.status_code != 200:
                    last_status = "SEARCH_UNAVAILABLE"
                    last_error = f"DuckDuckGo returned HTTP {res.status_code}"
                    break

                html_text = res.text
                if is_challenge_or_blocked_page(html_text):
                    trip_circuit(45.0)
                    last_status = "SEARCH_UNAVAILABLE"
                    last_error = "DuckDuckGo challenge/CAPTCHA encountered"
                    break

                results = parse_duckduckgo_html(html_text)
                if results:
                    out = {
                        "query": clean_query,
                        "results": results[:max_results],
                        "status": "OK",
                        "error": None,
                        "provider": "duckduckgo"
                    }
                    _search_cache[clean_query] = (now, out)
                    return out

                last_status = "NO_RESULTS"
                last_error = "No results found"
                break
        except httpx.TimeoutException as e:
            last_status = "SEARCH_TIMEOUT"
            last_error = f"DuckDuckGo request timed out after {req_timeout}s"
            if attempt < max_retries:
                await asyncio.sleep(SEARCH_RETRY_DELAY_SECONDS * (attempt + 1))
                continue
        except Exception as e:
            last_status = "SEARCH_UNAVAILABLE"
            last_error = f"DuckDuckGo connection error: {e}"
            if attempt < max_retries:
                await asyncio.sleep(SEARCH_RETRY_DELAY_SECONDS * (attempt + 1))
                continue

    out = {
        "query": clean_query,
        "results": [],
        "status": last_status,
        "error": last_error,
        "provider": "duckduckgo"
    }
    return out
