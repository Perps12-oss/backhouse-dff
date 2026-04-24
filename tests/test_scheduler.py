"""Tests for CerebroScheduler — persistence, CRUD, and fire logic."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from cerebro.core.scheduler import CerebroScheduler, ScheduledJob


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "scheduler_test.db"


@pytest.fixture()
def fired() -> list:
    return []


@pytest.fixture()
def sched(db_path: Path, fired: list) -> CerebroScheduler:
    return CerebroScheduler(db_path=db_path, on_scan_due=fired.append)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_instantiates_and_creates_db(db_path: Path, sched: CerebroScheduler) -> None:
    assert db_path.exists()
    assert isinstance(sched, CerebroScheduler)


def test_add_job_persists_and_list_returns_it(sched: CerebroScheduler) -> None:
    job = sched.add_job("daily", ["/tmp"], "files", 24.0)
    assert isinstance(job, ScheduledJob)
    assert job.id > 0
    jobs = sched.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].label == "daily"
    assert jobs[0].mode == "files"
    assert jobs[0].interval_hours == 24.0
    assert jobs[0].enabled is True


def test_remove_job_deletes_it(sched: CerebroScheduler) -> None:
    job = sched.add_job("temp", ["/tmp"], "files", 1.0)
    sched.remove_job(job.id)
    assert sched.list_jobs() == []


def test_toggle_job_flips_enabled(sched: CerebroScheduler) -> None:
    job = sched.add_job("weekly", ["/home"], "photos", 168.0)
    assert sched.list_jobs()[0].enabled is True
    sched.toggle_job(job.id, False)
    assert sched.list_jobs()[0].enabled is False
    sched.toggle_job(job.id, True)
    assert sched.list_jobs()[0].enabled is True


def test_check_and_fire_calls_callback_for_due_job(
    db_path: Path, fired: list
) -> None:
    sched = CerebroScheduler(db_path=db_path, on_scan_due=fired.append)
    job = sched.add_job("immediate", ["/tmp"], "files", 1.0)
    # Force next_run into the past
    import sqlite3
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE scheduled_jobs SET next_run = ? WHERE id = ?",
            (time.time() - 1.0, job.id),
        )
    sched._check_and_fire()
    assert len(fired) == 1
    assert fired[0].label == "immediate"


def test_check_and_fire_skips_disabled_job(
    db_path: Path, fired: list
) -> None:
    sched = CerebroScheduler(db_path=db_path, on_scan_due=fired.append)
    job = sched.add_job("disabled_job", ["/tmp"], "files", 1.0)
    sched.toggle_job(job.id, False)
    import sqlite3
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE scheduled_jobs SET next_run = ? WHERE id = ?",
            (time.time() - 1.0, job.id),
        )
    sched._check_and_fire()
    assert fired == []


def test_multiple_jobs_stored_and_retrieved(sched: CerebroScheduler) -> None:
    sched.add_job("job-a", ["/a"], "files", 1.0)
    sched.add_job("job-b", ["/b"], "photos", 2.0)
    sched.add_job("job-c", ["/c"], "music", 3.0)
    jobs = sched.list_jobs()
    assert len(jobs) == 3
    labels = {j.label for j in jobs}
    assert labels == {"job-a", "job-b", "job-c"}
