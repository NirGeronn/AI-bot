"""
Tool Router - Selects relevant tool groups based on user message content.
Reduces input tokens by only sending tools the model is likely to need.
"""
from __future__ import annotations

import re
import logging
from tools import (
    MEMORY_TOOLS, SYSTEM_TOOLS, WEB_TOOLS, GMAIL_TOOLS,
    CALENDAR_TOOLS, SCHEDULER_TOOLS, GOOGLE_TASK_TOOLS,
    TODO_TOOLS, WEATHER_TOOLS,
    UTILITY_TOOLS, TRENDS_TOOLS, BROWSER_TOOLS, CONTACT_TOOLS,
    ANTHROPIC_BILLING_TOOLS, FOOTBALL_TOOLS,
)

logger = logging.getLogger(__name__)

# Tool group registry
TOOL_GROUPS: dict[str, list[dict]] = {
    "memory":    MEMORY_TOOLS,
    "system":    SYSTEM_TOOLS,
    "web":       WEB_TOOLS,
    "gmail":     GMAIL_TOOLS,
    "calendar":  CALENDAR_TOOLS,
    "scheduler": SCHEDULER_TOOLS,
    "tasks":     GOOGLE_TASK_TOOLS,
    "todo":      TODO_TOOLS,
    "weather":   WEATHER_TOOLS,
    "utility":   UTILITY_TOOLS,
    "trends":    TRENDS_TOOLS,
    "browser":   BROWSER_TOOLS,
    "contacts":  CONTACT_TOOLS,
    "billing":   ANTHROPIC_BILLING_TOOLS,
    "football":  FOOTBALL_TOOLS,
}

# Groups always included
ALWAYS_INCLUDE = {"memory", "system", "web"}

# Keyword routing rules (group_name, pattern)
ROUTING_RULES: list[tuple[str, re.Pattern]] = [
    ("gmail", re.compile(
        r'(?:e?-?mail|inbox|gmail'
        r'|send\s+(?:a\s+)?(?:message|mail|email)'
        r'|check\s+(?:my\s+)?(?:inbox|mail|email)'
        r'|מייל|אימייל|דואר|תיבת\s+דואר)',
        re.IGNORECASE,
    )),
    ("calendar", re.compile(
        r'(?:calendar|event|meeting|appointment'
        r'|schedule(?!d?\s+message)'
        r'|busy|free\s+(?:time|slot)'
        r'|when\s+(?:is|am\s+i)|agenda'
        r'|what.?s\s+(?:on|happening)\s+(?:today|tomorrow|this\s+week|next\s+week)'
        r'|לוח\s*שנה|יומן|פגישה|אירוע)',
        re.IGNORECASE,
    )),
    ("scheduler", re.compile(
        r'(?:remind(?:er|me)?|timer|alarm|pomodoro'
        r'|schedule(?:d)?\s+message|daily\s+message|recurring'
        r'|set\s+(?:a\s+)?(?:reminder|timer|alarm)'
        r'|in\s+\d+\s+(?:minute|hour|second)'
        r'|every\s+(?:day|morning|evening|monday|tuesday|wednesday|thursday|friday|saturday|sunday)'
        r'|תזכורת|טיימר|תזכיר)',
        re.IGNORECASE,
    )),
    ("tasks", re.compile(
        r'(?:google\s+task|task\s+list|my\s+tasks?\b|משימות)',
        re.IGNORECASE,
    )),
    ("todo", re.compile(
        r'(?:todo|to-do|to\s+do\s+list|shopping\s+list|grocery|groceries'
        r'|checklist|רשימ[הת]|קניות)',
        re.IGNORECASE,
    )),
    ("weather", re.compile(
        r'(?:weather|temperature|forecast|rain|snow|sunny|cloudy|humid'
        r'|degrees|celsius|fahrenheit'
        r'|מזג\s+(?:ה)?אוויר|טמפרטורה|גשם|חם|קר)',
        re.IGNORECASE,
    )),
    ("utility", re.compile(
        r'(?:breach|hacked|pwned'
        r'|is\s+(?:it|.*)\s+down|is\s+.*\s+(?:up|working|online)'
        r'|speed\s*test|internet\s+speed|bandwidth'
        r'|בדיקת\s+מהירות|פריצ[הת])',
        re.IGNORECASE,
    )),
    ("trends", re.compile(
        r'(?:trending|github\s+trend|popular\s+repo'
        r'|what.?s\s+(?:trending|hot|popular)\s+(?:on\s+github|in\s+(?:tech|python|rust|go|javascript))'
        r'|טרנד)',
        re.IGNORECASE,
    )),
    ("browser", re.compile(
        r'(?:screenshot|playwright|browser'
        r'|click\s+(?:on|the)'
        r'|open\s+(?:in\s+)?(?:a\s+)?browser)',
        re.IGNORECASE,
    )),
    ("contacts", re.compile(
        r'(?:contact|phone\s+number|phone\s+book'
        r'|what.?s\s+.+(?:phone|number|email\s+address)'
        r'|find\s+.+contact|search\s+contact'
        r'|אנשי\s+קשר|טלפון\s+של|מספר\s+של)',
        re.IGNORECASE,
    )),
    ("football", re.compile(
        r'(?:football|soccer|premier\s+league|la\s+liga|champions\s+league'
        r'|europa\s+league|conference\s+league|bundesliga|serie\s+a|ligue\s+1'
        r'|kickoff|fixtures?|game\s+score'
        r'|(?:games?|matches?)\s+(?:today|tonight|tomorrow|this\s+week|on)'
        r'|(?:today|tonight|tomorrow|this\s+week)\'?s?\s+(?:games?|matches?|fixtures?)'
        r'|what.?s\s+on\s+(?:today|tonight)'
        r'|כדורגל|ליגת\s+העל|ליגת\s+האלופות|ליגה\s+אירופ'
        r'|מכבי\s+(?:חיפה|תל\s*אביב|נתניה|פתח)'
        r'|הפועל\s+(?:ת"א|ב"ש|חיפה|באר\s+שבע)|בית"?ר\s+(?:ירושלים)?'
        r'|משחק(?:ים|י|ות)?\b'
        r'|איזה\s+משחק|מי\s+משחק'
        r'|ריאל\s+מדריד|ברצלונה|מנצ\'?סטר|ארסנל|ליברפול|צ\'?לסי|טוטנהאם|באיירן)',
        re.IGNORECASE,
    )),
    ("billing", re.compile(
        r'(?:claude\s+(?:credit|balance|spend|usage|cost)'
        r'|anthropic\s+(?:credit|balance|spend|usage|cost)'
        r'|api\s+(?:credit|balance|spend|cost)'
        r'|how\s+much\s+(?:credit|money).*(?:claude|anthropic|api)'
        r'|remaining\s+(?:credit|balance))',
        re.IGNORECASE,
    )),
]

def select_tool_groups(
    user_text: str,
    image_data: dict | None = None,
    explicit_groups: list[str] | None = None,
) -> list[dict]:
    """Select relevant tool schemas based on user message content."""
    if explicit_groups is not None:
        groups = set(explicit_groups) | ALWAYS_INCLUDE
        tools = []
        for g in groups:
            tools.extend(TOOL_GROUPS.get(g, []))
        return tools

    selected = set(ALWAYS_INCLUDE)
    text = user_text or ""

    # Keyword matching
    for group_name, pattern in ROUTING_RULES:
        if pattern.search(text):
            selected.add(group_name)

    tools = []
    for g in selected:
        tools.extend(TOOL_GROUPS.get(g, []))

    logger.info(
        f"Tool router: {', '.join(sorted(selected))} = {len(tools)} tools"
    )
    return tools


# Format cache: frozenset of tool names -> formatted tools
_format_cache: dict[frozenset[str], list[dict]] = {}


def get_formatted_tools(client, tools: list[dict]) -> list[dict]:
    """Format tools for the current AI provider, with caching."""
    if not tools:
        return []
    key = frozenset(t["name"] for t in tools)
    if key not in _format_cache:
        _format_cache[key] = client.format_tools(tools)
    return _format_cache[key]
