"""
Tests for scheduler day mapping — PTB v22 uses a non-standard day numbering.
This is a known gotcha: 0=Sunday, 1=Monday, ..., 6=Saturday (NOT Python weekday).
We import directly from tools.scheduler to avoid the tools/__init__.py chain.
"""
from __future__ import annotations

import sys
import pytest

# Import scheduler directly, bypassing tools/__init__.py
from tools import scheduler as sched


def test_day_map_values():
    """DAY_MAP must match PTB v22 convention: 0=Sunday, ..., 6=Saturday."""
    assert sched.DAY_MAP["sunday"] == 0
    assert sched.DAY_MAP["monday"] == 1
    assert sched.DAY_MAP["tuesday"] == 2
    assert sched.DAY_MAP["wednesday"] == 3
    assert sched.DAY_MAP["thursday"] == 4
    assert sched.DAY_MAP["friday"] == 5
    assert sched.DAY_MAP["saturday"] == 6


def test_day_names_reverse_map():
    """DAY_NAMES reverse map is consistent with DAY_MAP."""
    for name, num in sched.DAY_MAP.items():
        assert num in sched.DAY_NAMES
        assert sched.DAY_NAMES[num].lower() == name


def test_all_seven_days_present():
    """All 7 days are mapped."""
    assert len(sched.DAY_MAP) == 7
    assert len(sched.DAY_NAMES) == 7
    assert set(sched.DAY_MAP.values()) == set(range(7))
