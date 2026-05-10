"""Tests for tool_router.py — focuses on the football routing rule we added,
plus regression coverage for previously-existing rules so future regex tweaks
can't silently break routing for common phrasings."""
from __future__ import annotations

import re
import pytest


def _load_router_patterns():
    """Extract the routing rules dict (group_name -> compiled pattern) from
    tool_router.py without importing the module — importing would pull
    tools/__init__ which needs API keys we don't have in CI."""
    import os, ast
    src = open(os.path.join(os.path.dirname(__file__), "..", "tool_router.py")).read()
    tree = ast.parse(src)

    # Find the `ROUTING_RULES[: type] = [ ... ]` (ast.Assign or ast.AnnAssign).
    for node in tree.body:
        target_name = None
        value_node = None
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "ROUTING_RULES":
                    target_name = t.id
                    value_node = node.value
                    break
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == "ROUTING_RULES":
            target_name = node.target.id
            value_node = node.value

        if target_name and value_node is not None:
            rules = []
            for elt in value_node.elts:
                # Each tuple: ("group_name", re.compile(r"...", re.IGNORECASE))
                group_name = elt.elts[0].value
                compile_call = elt.elts[1]
                pattern_arg = compile_call.args[0]
                if isinstance(pattern_arg, ast.Constant):
                    pattern = pattern_arg.value
                else:
                    pattern = ast.literal_eval(pattern_arg)
                rules.append((group_name, re.compile(pattern, re.IGNORECASE)))
            return dict(rules)
    raise RuntimeError("ROUTING_RULES not found in tool_router.py")


PATTERNS = _load_router_patterns()


def _matches(group: str, text: str) -> bool:
    return PATTERNS[group].search(text) is not None


# ─── Football pattern coverage (added recently; was the source of a bug) ───

@pytest.mark.parametrize("text", [
    "איזה משחקים יש היום?",       # the exact phrasing that previously slipped through
    "מה המשחקים הערב?",
    "מי משחק הערב",
    "כדורגל היום",
    "Premier League standings",
    "football games today",
    "matches today",
    "what's on tonight",
    "ברצלונה הפסידה אתמול",
    "ליגת העל תוצאות",
    "ליגת האלופות הערב",
    "מכבי תל אביב נגד הפועל",
])
def test_football_pattern_matches(text):
    assert _matches("football", text), f"Should match football: {text!r}"


@pytest.mark.parametrize("text", [
    "מה הטמפרטורה?",
    "what is the weather",
    "send an email",
    "remind me in 30 minutes",
    "set a timer for 5 minutes",
])
def test_football_pattern_does_not_overmatch(text):
    assert not _matches("football", text), f"Should NOT match football: {text!r}"


# ─── Regression coverage for other groups (so the broader football regex
#     above doesn't unintentionally swallow other groups' phrases) ───

@pytest.mark.parametrize("group,text", [
    ("weather", "what's the weather in tel aviv"),
    ("weather", "מה מזג האוויר היום"),
    ("gmail", "check my inbox"),
    ("gmail", "send an email to bob"),
    ("calendar", "what's on my calendar tomorrow"),
    ("scheduler", "remind me in 30 minutes"),
    ("scheduler", "set a 25 minute timer"),
    ("todo", "add buy milk to my shopping list"),
])
def test_other_groups_still_route(group, text):
    assert _matches(group, text), f"{group} should match: {text!r}"


# ─── Sanity: make sure the football group regex compiles with the broader
#     phrases it was extended to handle today. ───

def test_football_pattern_handles_tomorrow_variants():
    assert _matches("football", "games tomorrow")
    assert _matches("football", "tomorrow's games")
    assert _matches("football", "tonight's matches")


def test_football_group_is_registered():
    assert "football" in PATTERNS
