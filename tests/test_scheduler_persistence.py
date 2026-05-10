"""
Tests for scheduled jobs persistence (DB layer only — no PTB job queue needed).
Verifies that scheduled jobs are saved, loaded, and deleted correctly,
and that they're properly scoped per chat_id.
"""
from __future__ import annotations

import pytest
import json
import time

# Import scheduler directly, bypassing tools/__init__.py
from tools import scheduler as sched


USER_A = 111
USER_B = 222


@pytest.fixture
async def sched_db(tmp_db):
    """Initialize scheduler table alongside the main DB."""
    import memory
    await memory.init_db()

    # Patch scheduler's DB_PATH too
    original_db = sched.DB_PATH
    sched.DB_PATH = tmp_db
    await sched._ensure_table()

    yield tmp_db

    sched.DB_PATH = original_db


@pytest.mark.asyncio
async def test_save_and_load_daily_job(sched_db):
    """A daily job is saved and can be loaded back."""
    await sched._save_job(
        chat_id=USER_A,
        job_name="morning_briefing",
        job_type="daily",
        message="Give me a morning briefing",
        hour=7,
        minute=0,
        days=[1, 2, 3, 4, 5],
    )

    jobs = await sched._load_all_jobs()
    assert len(jobs) == 1
    job = jobs[0]
    assert job["chat_id"] == USER_A
    assert job["job_name"] == "morning_briefing"
    assert job["job_type"] == "daily"
    assert job["hour"] == 7
    assert job["minute"] == 0
    assert json.loads(job["days"]) == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_save_and_load_scheduled_job(sched_db):
    """A one-time scheduled job is saved and loadable."""
    await sched._save_job(
        chat_id=USER_A,
        job_name="buy_flowers",
        job_type="scheduled",
        message="Buy flowers for anniversary",
        fire_at="2026-05-01 15:00",
    )

    jobs = await sched._load_all_jobs()
    assert len(jobs) == 1
    assert jobs[0]["fire_at"] == "2026-05-01 15:00"
    assert jobs[0]["job_type"] == "scheduled"


@pytest.mark.asyncio
async def test_save_and_load_reminder(sched_db):
    """A reminder is saved with fire_at as a timestamp."""
    fire_ts = str(time.time() + 1800)
    await sched._save_job(
        chat_id=USER_A,
        job_name="reminder_123",
        job_type="reminder",
        message="Call mom",
        fire_at=fire_ts,
    )

    jobs = await sched._load_all_jobs()
    assert len(jobs) == 1
    assert jobs[0]["job_type"] == "reminder"
    assert jobs[0]["message"] == "Call mom"


@pytest.mark.asyncio
async def test_delete_job(sched_db):
    """Deleting a job removes it from the DB."""
    await sched._save_job(USER_A, "job1", "daily", "msg1", hour=8)
    await sched._save_job(USER_A, "job2", "daily", "msg2", hour=9)

    await sched._delete_job("job1")

    jobs = await sched._load_all_jobs()
    assert len(jobs) == 1
    assert jobs[0]["job_name"] == "job2"


@pytest.mark.asyncio
async def test_save_job_replaces_same_name(sched_db):
    """Saving a job with the same name replaces the previous one."""
    await sched._save_job(USER_A, "gym_reminder", "daily", "Go to gym v1", hour=7)
    await sched._save_job(USER_A, "gym_reminder", "daily", "Go to gym v2", hour=8)

    jobs = await sched._load_all_jobs()
    assert len(jobs) == 1
    assert jobs[0]["message"] == "Go to gym v2"
    assert jobs[0]["hour"] == 8


@pytest.mark.asyncio
async def test_jobs_isolated_by_chat_id(sched_db):
    """Jobs from different users are stored separately."""
    await sched._save_job(USER_A, "job_a", "daily", "A's job", hour=7)
    await sched._save_job(USER_B, "job_b", "daily", "B's job", hour=8)

    all_jobs = await sched._load_all_jobs()
    assert len(all_jobs) == 2

    a_jobs = [j for j in all_jobs if j["chat_id"] == USER_A]
    b_jobs = [j for j in all_jobs if j["chat_id"] == USER_B]
    assert len(a_jobs) == 1
    assert len(b_jobs) == 1
    assert a_jobs[0]["message"] == "A's job"
    assert b_jobs[0]["message"] == "B's job"


@pytest.mark.asyncio
async def test_delete_job_doesnt_affect_other_users(sched_db):
    """Deleting user A's job doesn't remove user B's job."""
    await sched._save_job(USER_A, "shared_name", "daily", "A's version", hour=7)
    await sched._save_job(USER_B, "b_job", "daily", "B's job", hour=8)

    await sched._delete_job("shared_name")

    jobs = await sched._load_all_jobs()
    assert len(jobs) == 1
    assert jobs[0]["chat_id"] == USER_B


@pytest.mark.asyncio
async def test_multiple_daily_jobs_for_same_user(sched_db):
    """A user can have multiple daily jobs."""
    await sched._save_job(USER_A, "morning", "daily", "Morning briefing", hour=7)
    await sched._save_job(USER_A, "evening", "daily", "Evening recap", hour=20)
    await sched._save_job(USER_A, "gym", "daily", "Gym reminder", hour=17, days=[0, 2, 4])

    jobs = await sched._load_all_jobs()
    user_a_jobs = [j for j in jobs if j["chat_id"] == USER_A]
    assert len(user_a_jobs) == 3


@pytest.mark.asyncio
async def test_days_serialization(sched_db):
    """Days array is correctly serialized to/from JSON."""
    days = [1, 3, 5]  # Mon, Wed, Fri
    await sched._save_job(USER_A, "weekday_job", "daily", "Weekday thing", hour=9, days=days)

    jobs = await sched._load_all_jobs()
    loaded_days = json.loads(jobs[0]["days"])
    assert loaded_days == [1, 3, 5]


@pytest.mark.asyncio
async def test_job_without_days_defaults_to_none(sched_db):
    """A daily job without days parameter stores None (meaning every day)."""
    await sched._save_job(USER_A, "everyday", "daily", "Daily thing", hour=9)

    jobs = await sched._load_all_jobs()
    assert jobs[0]["days"] is None
