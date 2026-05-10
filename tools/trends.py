import json
import logging
import httpx
from bs4 import BeautifulSoup
from config import BOT_USER_AGENT

logger = logging.getLogger(__name__)

TRENDS_TOOLS = [
    {
        "name": "github_trending",
        "description": (
            "Get trending repositories from GitHub. Shows the hottest repos right now. "
            "Can filter by programming language and time range. "
            "Use when the user asks 'what is trending on GitHub?', 'show me popular repos', "
            "'what is hot in Python/AI/Rust today?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "description": "Filter by programming language (e.g. 'python', 'javascript', 'rust', 'go'). Leave empty for all languages.",
                },
                "since": {
                    "type": "string",
                    "enum": ["daily", "weekly", "monthly"],
                    "description": "Time range for trending. Default: 'daily'.",
                },
            },
        },
    },
]


async def _scrape_github_trending(language: str = "", since: str = "daily") -> list[dict]:
    """Scrape GitHub trending page."""
    url = "https://github.com/trending"
    if language:
        url += f"/{language.lower()}"

    params = {"since": since}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params, headers={
            "User-Agent": f"Mozilla/5.0 (compatible; {BOT_USER_AGENT})",
        })
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    repos = []

    for article in soup.select("article.Box-row")[:15]:
        try:
            # Repo name
            name_el = article.select_one("h2 a")
            if not name_el:
                continue
            full_name = name_el.get("href", "").strip("/")

            # Description
            desc_el = article.select_one("p")
            description = desc_el.get_text(strip=True) if desc_el else ""

            # Language
            lang_el = article.select_one("[itemprop='programmingLanguage']")
            lang = lang_el.get_text(strip=True) if lang_el else ""

            # Stars
            stars_el = article.select("a.Link--muted")
            stars = ""
            forks = ""
            if len(stars_el) >= 1:
                stars = stars_el[0].get_text(strip=True).replace(",", "")
            if len(stars_el) >= 2:
                forks = stars_el[1].get_text(strip=True).replace(",", "")

            # Stars today/this week
            period_stars_el = article.select_one("span.d-inline-block.float-sm-right")
            period_stars = period_stars_el.get_text(strip=True) if period_stars_el else ""

            repos.append({
                "name": full_name,
                "description": description[:200],
                "language": lang,
                "stars": stars,
                "forks": forks,
                "period_stars": period_stars,
                "url": f"https://github.com/{full_name}",
            })
        except Exception as e:
            logger.warning(f"Failed to parse trending repo: {e}")
            continue

    return repos


async def execute_trends_tool(name: str, input_data: dict, chat_id: int) -> str:
    if name == "github_trending":
        language = input_data.get("language", "")
        since = input_data.get("since", "daily")

        try:
            repos = await _scrape_github_trending(language, since)

            if not repos:
                return json.dumps({"error": "No trending repos found. GitHub may have changed their page layout."})

            return json.dumps({
                "trending_repos": repos,
                "count": len(repos),
                "language": language or "all",
                "since": since,
                "instruction": "Present these trending repos in a clean, readable format for Telegram. Show rank, name, description, language, stars, and the period stars. Use the repo URL for reference.",
            })
        except Exception as e:
            logger.error(f"GitHub trending failed: {e}", exc_info=True)
            return json.dumps({"error": f"Failed to fetch GitHub trends: {str(e)}"})

    return json.dumps({"error": f"Unknown trends tool: {name}"})
