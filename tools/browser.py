"""
Browser Automation tool - Full Playwright-based web browsing.
Inspired by OpenClaw's browser tool. Supports navigation, interaction,
screenshots, and content extraction from JavaScript-rendered pages.
"""
import json
import base64
import asyncio
import logging

logger = logging.getLogger(__name__)

# Lazy browser instance
_browser = None
_playwright = None

# Mutable container so set_app works across imports
_state = {"app": None}


def set_app(app):
    _state["app"] = app


async def _send_screenshot(chat_id: int, screenshot_bytes: bytes) -> None:
    app = _state["app"]
    if not app:
        return
    import io
    await app.bot.send_photo(chat_id=chat_id, photo=io.BytesIO(screenshot_bytes))


async def _get_browser():
    """Get or create a shared browser instance."""
    global _browser, _playwright
    if _browser is None or not _browser.is_connected():
        from playwright.async_api import async_playwright
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        logger.info("Browser launched")
    return _browser


BROWSER_TOOLS = [
    {
        "name": "browser_navigate",
        "description": (
            "Navigate to a URL using a real browser (Playwright/Chromium). "
            "Use this instead of browse_url when you need to: "
            "(1) load JavaScript-rendered pages (SPAs, React apps), "
            "(2) interact with dynamic content, "
            "(3) take screenshots, "
            "(4) access pages that block simple HTTP requests. "
            "Returns the rendered page text content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to navigate to",
                },
                "wait_for": {
                    "type": "string",
                    "description": "Optional CSS selector to wait for before extracting content. E.g. '.main-content' or '#results'.",
                },
                "screenshot": {
                    "type": "boolean",
                    "description": "If true, also takes a screenshot and returns it. Default false.",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "browser_click",
        "description": (
            "Click an element on the current browser page. "
            "Use after browser_navigate to interact with buttons, links, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector of the element to click. E.g. 'button.submit', 'a[href=\"/login\"]', '#next-page'.",
                },
                "text": {
                    "type": "string",
                    "description": "Alternative: click element containing this text. E.g. 'Sign In', 'Next Page'.",
                },
            },
        },
    },
    {
        "name": "browser_type",
        "description": "Type text into an input field on the current browser page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector of the input field. E.g. 'input[name=\"search\"]', '#email'.",
                },
                "text": {
                    "type": "string",
                    "description": "The text to type into the field.",
                },
                "press_enter": {
                    "type": "boolean",
                    "description": "If true, press Enter after typing. Default false.",
                },
            },
            "required": ["selector", "text"],
        },
    },
    {
        "name": "browser_screenshot",
        "description": "Take a screenshot of the current browser page. The image will be sent to the chat.",
        "input_schema": {
            "type": "object",
            "properties": {
                "full_page": {
                    "type": "boolean",
                    "description": "If true, capture the full page including scrollable area. Default false (viewport only).",
                },
            },
        },
    },
    {
        "name": "browser_get_content",
        "description": "Get the current page's text content (useful after clicking/navigating).",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]

# Track the current page per chat
_pages = {}


async def _get_page(chat_id: int):
    """Get or create a page for a chat session."""
    if chat_id not in _pages or _pages[chat_id].is_closed():
        browser = await _get_browser()
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        _pages[chat_id] = await context.new_page()
    return _pages[chat_id]


async def _extract_page_text(page, max_chars: int = 8000) -> str:
    """Extract readable text from the current page."""
    text = await page.evaluate("""() => {
        // Remove unwanted elements
        const remove = ['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe', 'noscript', 'svg'];
        remove.forEach(tag => document.querySelectorAll(tag).forEach(el => el.remove()));

        // Try main content area first
        const main = document.querySelector('main') || document.querySelector('article') ||
                     document.querySelector('[role="main"]') || document.body;
        return main.innerText;
    }""")

    # Clean up
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = "\n".join(lines)

    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[...truncated]"

    return text


async def execute_browser_tool(name: str, input_data: dict, chat_id: int) -> str:
    try:
        if name == "browser_navigate":
            url = input_data["url"]
            wait_for = input_data.get("wait_for")
            take_screenshot = input_data.get("screenshot", False)

            page = await _get_page(chat_id)

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Wait for specific element if requested
            if wait_for:
                try:
                    await page.wait_for_selector(wait_for, timeout=10000)
                except Exception:
                    pass  # Continue even if selector not found

            # Small delay for JS rendering
            await asyncio.sleep(1)

            title = await page.title()
            text = await _extract_page_text(page)

            result = {"url": url, "title": title, "content": text}

            if take_screenshot:
                screenshot_bytes = await page.screenshot()
                result["screenshot_base64"] = base64.b64encode(screenshot_bytes).decode()
                result["screenshot_note"] = "Screenshot captured"

            return json.dumps(result)

        elif name == "browser_click":
            page = await _get_page(chat_id)
            selector = input_data.get("selector")
            text = input_data.get("text")

            if text and not selector:
                # Click by text content
                await page.get_by_text(text, exact=False).first.click(timeout=10000)
            elif selector:
                await page.click(selector, timeout=10000)
            else:
                return json.dumps({"error": "Provide either 'selector' or 'text' to click"})

            await asyncio.sleep(1)
            new_url = page.url
            content = await _extract_page_text(page)

            return json.dumps({"status": "clicked", "current_url": new_url, "content": content[:4000]})

        elif name == "browser_type":
            page = await _get_page(chat_id)
            selector = input_data["selector"]
            text = input_data["text"]
            press_enter = input_data.get("press_enter", False)

            await page.fill(selector, text, timeout=10000)
            if press_enter:
                await page.press(selector, "Enter")
                await asyncio.sleep(1)

            return json.dumps({"status": "typed", "current_url": page.url})

        elif name == "browser_screenshot":
            page = await _get_page(chat_id)
            full_page = input_data.get("full_page", False)

            screenshot_bytes = await page.screenshot(full_page=full_page)

            await _send_screenshot(chat_id, screenshot_bytes)

            return json.dumps({
                "status": "screenshot_taken",
                "current_url": page.url,
                "note": "Screenshot captured and sent in the chat.",
            })

        elif name == "browser_get_content":
            page = await _get_page(chat_id)
            title = await page.title()
            text = await _extract_page_text(page)

            return json.dumps({"url": page.url, "title": title, "content": text})

    except Exception as e:
        logger.error(f"Browser tool error ({name}): {e}")
        return json.dumps({"error": f"Browser error: {str(e)}"})

    return json.dumps({"error": f"Unknown browser tool: {name}"})
