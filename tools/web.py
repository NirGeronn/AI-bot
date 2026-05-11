import json
import asyncio
import logging
import httpx
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from ddgs import DDGS

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}
_TIMEOUT = 15
_MAX_PAGE_CHARS = 8000
_JS_FALLBACK_MIN_CHARS = 300

WEB_TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web using DuckDuckGo. Returns top results with titles, URLs, and snippets. IMPORTANT: You MUST call this tool before answering any factual question (people, events, dates, stats, news, prices, products, science, tech). Never answer factual questions from memory alone.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of results (default 8, max 10)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "browse_url",
        "description": "Fetch and read a web page. Extracts the main text content from any URL. Use this to read articles, documentation, product pages, news, etc. Use after web_search to read specific result pages for verification.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch and read",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "web_research",
        "description": "Deep multi-source web research. Searches the web and reads up to 5 pages from at least 3 different domains for cross-referencing. Use this for complex factual questions that benefit from comparing multiple sources. Returns search results plus full page content from diverse sources.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The research question or topic",
                },
            },
            "required": ["query"],
        },
    },
]


def _extract_domain(url: str) -> str:
    """Extract the base domain from a URL (e.g. 'en.wikipedia.org' -> 'wikipedia.org')."""
    try:
        host = urlparse(url).hostname or ""
        parts = host.split(".")
        # Get last two parts for the base domain (e.g. wikipedia.org)
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return host
    except Exception:
        return url


def _select_diverse_urls(results: list[dict], max_urls: int = 5, min_domains: int = 3) -> list[str]:
    """Select URLs ensuring diversity across domains.

    Picks URLs from as many different domains as possible,
    prioritizing results that appear earlier in search rankings.
    """
    selected = []
    domains_seen = set()

    # First pass: pick one URL per unique domain
    for r in results:
        url = r.get("url", "")
        if not url:
            continue
        domain = _extract_domain(url)
        if domain not in domains_seen:
            selected.append(url)
            domains_seen.add(domain)
        if len(selected) >= max_urls:
            break

    # If we still have room and didn't reach max_urls, fill with remaining
    if len(selected) < max_urls:
        for r in results:
            url = r.get("url", "")
            if url and url not in selected:
                selected.append(url)
            if len(selected) >= max_urls:
                break

    return selected


async def _fetch_via_playwright(url: str) -> dict:
    """Render a page with Playwright for JS-heavy or blocked sites."""
    try:
        from tools.browser import _get_page, _extract_page_text
        page = await _get_page(0)
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1.5)
        title = await page.title()
        text = await _extract_page_text(page, max_chars=_MAX_PAGE_CHARS)
        return {"url": url, "title": title, "content": text, "rendered": "playwright"}
    except Exception as e:
        logger.warning(f"Playwright fallback failed for {url}: {type(e).__name__}: {e}")
        return {"url": url, "error": f"Playwright fallback failed: {type(e).__name__}: {e}"}


async def _fetch_and_extract(url: str) -> dict:
    """Fetch a URL and extract readable text content.

    Falls back to Playwright for JS-rendered pages or when the simple HTTP
    fetch is blocked (403) / returns too little content.
    """
    http_err: str | None = None
    try:
        async with httpx.AsyncClient(
            headers=_HEADERS,
            timeout=_TIMEOUT,
            follow_redirects=True,
            max_redirects=5,
        ) as client:
            resp = await client.get(url)

        if resp.status_code in (401, 403, 429) or resp.status_code >= 500:
            logger.info(f"browse_url got {resp.status_code} for {url}, trying Playwright")
            return await _fetch_via_playwright(url)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type and "text/plain" not in content_type:
            return {"url": url, "error": f"Not a text page: {content_type}"}

        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "aside",
                         "iframe", "noscript", "svg", "form", "button"]):
            tag.decompose()

        main = soup.find("main") or soup.find("article") or soup.find("div", {"role": "main"})
        if main:
            text = main.get_text(separator="\n", strip=True)
        else:
            text = soup.get_text(separator="\n", strip=True)

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = "\n".join(lines)

        title = soup.title.string.strip() if soup.title and soup.title.string else ""

        if len(text) < _JS_FALLBACK_MIN_CHARS:
            logger.info(f"browse_url got only {len(text)} chars from {url}, trying Playwright")
            pw = await _fetch_via_playwright(url)
            if "error" not in pw and len(pw.get("content", "")) > len(text):
                return pw

        if len(text) > _MAX_PAGE_CHARS:
            text = text[:_MAX_PAGE_CHARS] + "\n\n[...truncated]"

        return {"url": url, "title": title, "content": text}

    except httpx.TimeoutException:
        http_err = "Timed out fetching page via HTTP"
    except Exception as e:
        http_err = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__

    logger.info(f"browse_url HTTP failed for {url} ({http_err}), trying Playwright")
    pw = await _fetch_via_playwright(url)
    if "error" not in pw:
        return pw
    return {"url": url, "error": http_err or pw.get("error")}


def _search_ddg(query: str, max_results: int = 8) -> list[dict]:
    """Run DuckDuckGo search and return formatted results."""
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("href", ""),
            "snippet": r.get("body", ""),
        }
        for r in results
    ]


async def execute_web_tool(name: str, input_data: dict, chat_id: int) -> str:
    if name == "web_search":
        query = input_data["query"]
        max_results = min(input_data.get("max_results", 8), 10)
        try:
            results = _search_ddg(query, max_results)
            return json.dumps({"results": results})
        except Exception as e:
            # "No results found" isn't really a tool failure — DDGS raises it
            # when every backend returns empty. Treat as empty results so the
            # model retries with a different query instead of bailing.
            msg = str(e).lower()
            if "no results" in msg or "no result" in msg:
                return json.dumps({"results": [], "note": "0 hits — try a different query"})
            return json.dumps({"error": f"Search failed: {str(e)}"})

    elif name == "browse_url":
        url = input_data["url"]
        result = await _fetch_and_extract(url)
        return json.dumps(result)

    elif name == "web_research":
        query = input_data["query"]
        try:
            # Step 1: Search
            search_results = _search_ddg(query, 10)

            # Step 2: Pick up to 5 URLs from at least 3 different domains
            urls = _select_diverse_urls(search_results, max_urls=5, min_domains=3)

            # Step 3: Read selected pages in parallel
            page_tasks = [_fetch_and_extract(url) for url in urls]
            pages = await asyncio.gather(*page_tasks, return_exceptions=True)

            page_contents = []
            for p in pages:
                if isinstance(p, Exception):
                    page_contents.append({"error": str(p)})
                else:
                    page_contents.append(p)

            domains_read = list(set(_extract_domain(u) for u in urls))

            return json.dumps({
                "search_results": search_results,
                "pages_read": page_contents,
                "domains_consulted": domains_read,
                "note": f"Read {len(page_contents)} pages from {len(domains_read)} different domains. Base your answer ONLY on this data.",
            })
        except Exception as e:
            return json.dumps({"error": f"Research failed: {str(e)}"})

    return json.dumps({"error": f"Unknown web tool: {name}"})
