import json, time, hashlib, logging, re, asyncio
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ..core.utils import get_http_client

logger = logging.getLogger("xens.tools.web")

_CACHE_DIR = Path.home() / ".xens" / "cache" / "web"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_CACHE_TTL = 3600
_MAX_CACHE_SIZE = 50
_RATE_LIMIT = 3.0
_last_request = 0.0
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

def _cache_key(url):
    return hashlib.sha256(url.encode()).hexdigest()[:16]

def _cache_get(key):
    cache_file = _CACHE_DIR / f"{key}.json"
    if not cache_file.exists():
        return None
    try:
        if time.time() - cache_file.stat().st_mtime > _CACHE_TTL:
            cache_file.unlink(missing_ok=True)
            return None
    except FileNotFoundError:
        return None
    try:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    except:
        return None

def _cache_set(key, data):
    try:
        cache_files = sorted(_CACHE_DIR.iterdir(), key=lambda f: f.stat().st_mtime)
        while len(cache_files) >= _MAX_CACHE_SIZE:
            cache_files[0].unlink()
            cache_files = cache_files[1:]
        cache_file = _CACHE_DIR / f"{key}.json"
        cache_file.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        logger.debug(f"Cache write failed: {e}")

async def _rate_limit():
    global _last_request
    now = time.time()
    elapsed = now - _last_request
    if elapsed < _RATE_LIMIT:
        await asyncio.sleep(_RATE_LIMIT - elapsed)
    _last_request = time.time()

def _strip_html(html):
    text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), text)
    return text.strip()[:8000]

async def web_search(query: str, num_results: int = 5) -> str:
    if not query or not query.strip():
        return json.dumps({"error": "Search query is required", "success": False})

    num_results = max(1, min(num_results, 15))
    cache_key = _cache_key(f"search:{query.strip().lower()}:{num_results}")
    cached = _cache_get(cache_key)
    if cached:
        logger.debug(f"Search cache hit for '{query[:30]}'")
        return json.dumps(cached)

    results = []

    # Primary: DuckDuckGo Lite API
    try:
        ddg_results = await _search_ddg(query, num_results)
        if ddg_results:
            results = ddg_results
    except Exception as e:
        logger.warning(f"DDG search failed: {e}")

    # Fallback: scraping
    if not results:
        try:
            scrape_results = await _search_scrape(query, num_results)
            if scrape_results:
                results = scrape_results
        except Exception as e:
            logger.warning(f"Scrape search failed: {e}")

    if not results:
        return json.dumps({"error": "All search sources failed", "success": False})

    results = results[:num_results]
    resp = {"success": True, "query": query, "results": results, "count": len(results)}
    _cache_set(cache_key, resp)
    return json.dumps(resp)

async def _search_ddg(query, num_results):
    url = "https://lite.duckduckgo.com/lite/"
    try:
        r = await get_http_client().post(url, data={"q": query}, timeout=10)
        r.raise_for_status()
        html = r.text
    except:
        return []

    results = []
    for block in re.findall(r'<tr[^>]*>.*?</tr>', html, re.DOTALL)[:num_results * 2]:
        title_m = re.search(r'class="result-link"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL)
        snippet_m = re.search(r'class="result-snippet"[^>]*>(.*?)</td>', block, re.DOTALL)
        if title_m:
            url = title_m.group(1)
            title = _strip_html(title_m.group(2))
            snippet = _strip_html(snippet_m.group(1)) if snippet_m else ""
            results.append({"title": title, "url": url, "snippet": snippet})
    return results

async def _search_scrape(query, num_results):
    url = f"https://lite.duckduckgo.com/lite/?q={query.replace(' ', '+')}"
    try:
        r = await get_http_client().get(url, timeout=10)
        r.raise_for_status()
    except:
        return []

    results = []
    for block in re.findall(r'<tr[^>]*>.*?</tr>', r.text, re.DOTALL)[:num_results * 2]:
        link_m = re.search(r'href="(https?://[^"]+)"', block)
        text_m = re.search(r'>(.*?)</a>', block)
        if link_m:
            url = link_m.group(1)
            text = _strip_html(text_m.group(1)) if text_m else url
            results.append({"title": text, "url": url, "snippet": ""})
    return results

async def web_fetch(url: str, max_chars: int = 8000, format: str = "markdown") -> str:
    if not url:
        return json.dumps({"error": "URL is required", "success": False})

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return json.dumps({"error": "URL must start with http:// or https://", "success": False})

    max_chars = max(1000, min(max_chars, 50000))

    cache_key = _cache_key(f"fetch:{url}:{max_chars}:{format}")
    cached = _cache_get(cache_key)
    if cached:
        logger.debug(f"Fetch cache hit for '{url[:40]}'")
        return json.dumps(cached)

    await _rate_limit()

    try:
        r = await get_http_client().get(url, timeout=30)
        r.raise_for_status()

        content_type = r.headers.get("content-type", "")
        text = r.text

        if "application/json" in content_type:
            try:
                data = r.json()
                content = json.dumps(data, indent=2, ensure_ascii=False)
            except:
                content = text
        elif format == "markdown":
            content = _html_to_markdown(text)
        else:
            content = _strip_html(text)

        content = content[:max_chars]
        resp = {
            "success": True,
            "url": str(r.url),
            "status": r.status_code,
            "content_type": content_type.split(";")[0],
            "content": content,
            "truncated": len(content) >= max_chars,
        }
        _cache_set(cache_key, resp)
        return json.dumps(resp)

    except httpx.TimeoutException:
        return json.dumps({"error": f"Request timed out for '{url[:60]}'", "success": False})
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"HTTP {e.response.status_code} for '{url[:60]}'", "success": False})
    except httpx.RequestError as e:
        return json.dumps({"error": f"Connection failed for '{url[:60]}': {e.__class__.__name__}", "success": False})
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch '{url[:60]}': {e}", "success": False})

def _html_to_markdown(html):
    text = _strip_html(html)
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        line = line.strip()
        if line:
            cleaned.append(line)
    return "\n\n".join(cleaned)


