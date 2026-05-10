"""
Skills loader - reads skill markdown files from the skills/ directory
and composes them into the system prompt. Inspired by OpenClaw's skills system.
"""
from __future__ import annotations

import os
import logging

logger = logging.getLogger(__name__)

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")


def _parse_skill(filepath: str) -> dict | None:
    """Parse a skill markdown file with YAML frontmatter."""
    try:
        with open(filepath, "r") as f:
            content = f.read()
    except Exception as e:
        logger.warning(f"Failed to read skill file {filepath}: {e}")
        return None

    # Parse frontmatter
    meta = {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1].strip()
            body = parts[2].strip()
            for line in frontmatter.split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip()
                    value = value.strip()
                    # Parse arrays like [a, b, c]
                    if value.startswith("[") and value.endswith("]"):
                        value = [v.strip().strip("'\"") for v in value[1:-1].split(",")]
                    elif value.lower() == "true":
                        value = True
                    elif value.lower() == "false":
                        value = False
                    meta[key] = value

    return {
        "name": meta.get("name", os.path.basename(filepath).replace(".md", "")),
        "description": meta.get("description", ""),
        "always": meta.get("always", False),
        "tools": meta.get("tools", []),
        "body": body,
    }


def load_all_skills() -> list[dict]:
    """Load all skill files from the skills directory."""
    skills = []
    if not os.path.isdir(SKILLS_DIR):
        logger.warning(f"Skills directory not found: {SKILLS_DIR}")
        return skills

    for filename in sorted(os.listdir(SKILLS_DIR)):
        if not filename.endswith(".md"):
            continue
        filepath = os.path.join(SKILLS_DIR, filename)
        skill = _parse_skill(filepath)
        if skill:
            skills.append(skill)
            logger.debug(f"Loaded skill: {skill['name']}")

    logger.info(f"Loaded {len(skills)} skills")
    return skills


def compose_system_prompt(skills: list[dict] | None = None) -> str:
    """Compose the system prompt from skill files."""
    from config import BOT_OWNER_NAME, USER_TIMEZONE, BOT_LANGUAGE, MODEL

    if skills is None:
        skills = load_all_skills()

    parts = []

    # Soul skill (core identity) goes first
    soul_skills = [s for s in skills if s["name"] == "soul"]
    other_skills = [s for s in skills if s["name"] != "soul"]

    for skill in soul_skills:
        parts.append(skill["body"])

    # Add capability sections
    if other_skills:
        parts.append("\nYou have access to tools - use them when needed:\n")
        for skill in other_skills:
            parts.append(skill["body"])

    prompt = "\n\n".join(parts)

    # Template variable substitution
    prompt = prompt.replace("{owner_name}", BOT_OWNER_NAME)
    prompt = prompt.replace("{timezone}", USER_TIMEZONE)
    prompt = prompt.replace("{language}", BOT_LANGUAGE)
    prompt = prompt.replace("{model}", MODEL)

    return prompt


# Cache skills at import time
_cached_skills = None
_cached_prompt = None


def get_base_system_prompt() -> str:
    """Get the base system prompt, cached after first load."""
    global _cached_skills, _cached_prompt
    if _cached_prompt is None:
        _cached_skills = load_all_skills()
        _cached_prompt = compose_system_prompt(_cached_skills)
    return _cached_prompt


def reload_skills():
    """Force reload of skills (call after editing skill files)."""
    global _cached_skills, _cached_prompt
    _cached_skills = None
    _cached_prompt = None
    return get_base_system_prompt()
