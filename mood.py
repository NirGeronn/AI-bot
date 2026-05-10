"""
Mood system — varies the bot's personality based on time of day and day of week.
Inspired by Leon AI's mood architecture.
"""
import random
from datetime import datetime
from zoneinfo import ZoneInfo
from config import USER_TIMEZONE

_TZ = ZoneInfo(USER_TIMEZONE)

MOODS = {
    "default": {
        "label": "default",
        "tone": "Warm, upbeat, and practical.",
        "energy": "Medium-high.",
        "humor": "Light and friendly, uses occasional wit.",
        "style": "Encouraging, proactive, solution-oriented.",
        "avoid": "Being overly formal or robotic.",
    },
    "focused": {
        "label": "focused",
        "tone": "Sharp, efficient, and direct.",
        "energy": "High.",
        "humor": "Minimal — only if it helps make a point.",
        "style": "Get straight to the point. No fluff. Prioritize action over explanation.",
        "avoid": "Long intros, excessive pleasantries, over-explaining.",
    },
    "chill": {
        "label": "chill",
        "tone": "Relaxed, casual, laid-back.",
        "energy": "Low-medium.",
        "humor": "Easygoing, conversational humor.",
        "style": "Take it easy. Be a friend hanging out. No rush.",
        "avoid": "Being pushy, over-structured, or overly formal.",
    },
    "tired": {
        "label": "tired",
        "tone": "Slightly slower, still helpful but more mellow.",
        "energy": "Low.",
        "humor": "Dry, understated.",
        "style": "Still helpful, but shorter responses. Conserve energy. Acknowledge it if asked.",
        "avoid": "Being overly enthusiastic or hyperactive.",
    },
}


def pick_mood() -> dict:
    """Select a mood based on time of day and day of week (Israel time)."""
    now_local = datetime.now(_TZ)
    hour = now_local.hour
    weekday = now_local.weekday()  # 0=Monday, 6=Sunday

    # Weighted random selection based on context
    weights = {"default": 50, "focused": 20, "chill": 20, "tired": 10}

    # Time-based adjustments
    if 6 <= hour <= 9:
        # Morning — focused energy
        weights["focused"] = 45
        weights["default"] = 40
        weights["chill"] = 10
        weights["tired"] = 5
    elif 10 <= hour <= 12:
        # Mid-morning — peak productivity
        weights["focused"] = 50
        weights["default"] = 35
        weights["chill"] = 10
        weights["tired"] = 5
    elif 13 <= hour <= 14:
        # Post-lunch slump
        weights["tired"] = 35
        weights["chill"] = 30
        weights["default"] = 25
        weights["focused"] = 10
    elif 15 <= hour <= 18:
        # Afternoon — back to normal
        weights["default"] = 45
        weights["focused"] = 25
        weights["chill"] = 20
        weights["tired"] = 10
    elif 19 <= hour <= 22:
        # Evening — wind down
        weights["chill"] = 45
        weights["default"] = 35
        weights["focused"] = 10
        weights["tired"] = 10
    elif hour >= 23 or hour < 6:
        # Late night
        weights["tired"] = 40
        weights["chill"] = 35
        weights["default"] = 15
        weights["focused"] = 10

    # Day-based adjustments
    if weekday == 6:  # Sunday (first work day in Israel)
        weights["focused"] = max(weights["focused"], 40)
    elif weekday == 4:  # Friday
        weights["chill"] = max(weights["chill"], 45)
        weights["focused"] = min(weights["focused"], 15)
    elif weekday == 5:  # Saturday (Shabbat)
        weights["chill"] = max(weights["chill"], 50)
        weights["focused"] = min(weights["focused"], 10)

    # Weighted random choice
    mood_names = list(weights.keys())
    mood_weights = [weights[m] for m in mood_names]
    chosen = random.choices(mood_names, weights=mood_weights, k=1)[0]

    return MOODS[chosen]


def mood_prompt_section() -> str:
    """Generate the mood section to inject into the system prompt."""
    mood = pick_mood()

    return (
        f"\nCurrent mood: {mood['label']}\n"
        f"- Tone: {mood['tone']}\n"
        f"- Energy: {mood['energy']}\n"
        f"- Humor: {mood['humor']}\n"
        f"- Style: {mood['style']}\n"
        f"- Avoid: {mood['avoid']}\n"
        f"Subtly adapt your responses to match this mood. Don't mention the mood explicitly unless asked."
    )
