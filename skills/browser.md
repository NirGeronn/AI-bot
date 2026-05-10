---
name: browser
description: Full browser automation with Playwright
tools: [browser_navigate, browser_click, browser_type, browser_screenshot, browser_get_content]
---
You have a full Chromium browser you can control:
- Navigate to URLs and get JavaScript-rendered content (browser_navigate) — use this for SPAs, React apps, or pages that block simple HTTP requests
- Click buttons and links (browser_click)
- Type into input fields and submit forms (browser_type)
- Take screenshots of pages (browser_screenshot)
- Get the current page content after interactions (browser_get_content)

Use the browser tools when browse_url doesn't work (e.g. JavaScript-heavy sites, login walls, dynamic content). For simple static pages, browse_url is faster.
