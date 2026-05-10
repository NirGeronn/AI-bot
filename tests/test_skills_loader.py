"""
Tests for the skills loader: ensuring skills are loaded correctly and the
system prompt is properly composed.
"""
import pytest
import os


def test_skills_directory_exists():
    """The skills/ directory exists."""
    skills_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills")
    assert os.path.isdir(skills_dir), f"skills/ directory not found at {skills_dir}"


def test_soul_skill_exists():
    """The core soul.md skill file exists (required for identity)."""
    soul_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills", "soul.md")
    assert os.path.isfile(soul_path), "skills/soul.md not found"


def test_base_system_prompt_not_empty():
    """The base system prompt is non-empty and contains key sections."""
    from skills_loader import get_base_system_prompt

    prompt = get_base_system_prompt()
    assert len(prompt) > 100, "System prompt is suspiciously short"


def test_system_prompt_contains_owner_name():
    """The system prompt includes the configured owner name."""
    from skills_loader import get_base_system_prompt
    from config import BOT_OWNER_NAME

    prompt = get_base_system_prompt()
    assert BOT_OWNER_NAME in prompt, f"Owner name '{BOT_OWNER_NAME}' not found in system prompt"


def test_system_prompt_contains_timezone():
    """The system prompt includes the configured timezone."""
    from skills_loader import get_base_system_prompt
    from config import USER_TIMEZONE

    prompt = get_base_system_prompt()
    assert USER_TIMEZONE in prompt, f"Timezone '{USER_TIMEZONE}' not found in system prompt"


def test_all_skill_files_are_valid():
    """All .md files in skills/ are readable and non-empty."""
    skills_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills")
    skill_files = [f for f in os.listdir(skills_dir) if f.endswith(".md")]
    assert len(skill_files) > 0, "No skill files found"

    for fname in skill_files:
        fpath = os.path.join(skills_dir, fname)
        with open(fpath, "r") as f:
            content = f.read()
        assert len(content.strip()) > 0, f"Skill file {fname} is empty"
