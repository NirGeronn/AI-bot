"""Skill creator tool — writes a new markdown file under skills/ and reloads."""
from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills")

SKILL_CREATOR_TOOLS = [
    {
        "name": "create_skill",
        "description": (
            "Create a new skill file in skills/ so future conversations have a new "
            "reusable capability. Reloads the in-memory skills cache so it takes "
            "effect immediately. Use only for genuinely reusable capabilities — "
            "for one-off facts, use the memory tool instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Short kebab-case name (no .md). Example: youtube-autosummary",
                },
                "description": {
                    "type": "string",
                    "description": "One-line description for the frontmatter",
                },
                "body": {
                    "type": "string",
                    "description": "Markdown body explaining when and how to use this skill",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Overwrite if a skill with this name already exists (default false)",
                },
            },
            "required": ["name", "description", "body"],
        },
    },
]

_SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9\-_]{0,40}$")


async def execute_skill_creator_tool(name: str, input_data: dict, chat_id: int) -> str:
    if name != "create_skill":
        return json.dumps({"error": f"Unknown tool: {name}"})
    skill_name = (input_data.get("name") or "").strip().lower()
    desc = (input_data.get("description") or "").strip()
    body = (input_data.get("body") or "").strip()
    overwrite = bool(input_data.get("overwrite"))

    if not _SAFE_NAME.match(skill_name):
        return json.dumps({"error": "name must be lowercase kebab-case, 1-40 chars"})
    if not desc or not body:
        return json.dumps({"error": "description and body are required"})

    os.makedirs(SKILLS_DIR, exist_ok=True)
    path = os.path.join(SKILLS_DIR, f"{skill_name}.md")
    if os.path.exists(path) and not overwrite:
        return json.dumps({"error": f"skill '{skill_name}' already exists; pass overwrite=true to replace"})

    content = f"---\nname: {skill_name}\ndescription: {desc}\n---\n\n{body}\n"
    try:
        with open(path, "w") as f:
            f.write(content)
    except Exception as e:
        return json.dumps({"error": f"write failed: {e}"})

    try:
        from skills_loader import reload_skills
        reload_skills()
    except Exception as e:
        logger.warning(f"reload_skills failed after create_skill: {e}")

    return json.dumps({"ok": True, "path": path, "name": skill_name})
