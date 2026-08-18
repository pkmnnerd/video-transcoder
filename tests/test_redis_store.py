"""Tests for the JobStore using a fakeredis in-memory backend."""

import pytest

from app.models.job import JobStatus, TranscodeJob
from app.services.redis_store import JobStore


@pytest.fixture
def store():
    import fakeredis.aioredis

    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return JobStore(r)


async def test_save_and_get(store):
    job = TranscodeJob(original_filename="a.mp4", input_path="/x/a.mp4")
    await store.save(job)
    got = await store.get(job.id)
    assert got.id == job.id
    assert got.status == JobStatus.PENDING


async def test_update_fields(store):
    job = TranscodeJob(original_filename="a.mp4", input_path="/x/a.mp4")
    await store.save(job)
    await store.update(job.id, status=JobStatus.RUNNING, progress=42.5)
    got = await store.get(job.id)
    assert got.status == JobStatus.RUNNING
    assert got.progress == 42.5


async def test_request_abort(store):
    job = TranscodeJob(original_filename="a.mp4", input_path="/x/a.mp4")
    await store.save(job)
    assert await store.request_abort(job.id) is True
    assert await store.is_abort_requested(job.id) is True
    await store.clear_abort(job.id)
    assert await store.is_abort_requested(job.id) is False


async def test_request_abort_terminal_rejected(store):
    job = TranscodeJob(original_filename="a.mp4", input_path="/x/a.mp4")
    await store.save(job)
    await store.update(job.id, status=JobStatus.COMPLETED)
    assert await store.request_abort(job.id) is False


async def test_get_all_sorted_newest_first(store):
    j1 = TranscodeJob(original_filename="a.mp4", input_path="/x/a.mp4")
    j2 = TranscodeJob(original_filename="b.mp4", input_path="/x/b.mp4")
    await store.save(j1)
    await store.save(j2)
    jobs = await store.get_all()
    assert len(jobs) == 2
    assert jobs[0].id == j2.id  # newest first


async def test_delete(store):
    job = TranscodeJob(original_filename="a.mp4", input_path="/x/a.mp4")
    await store.save(job)
    await store.delete(job.id)
    assert await store.get(job.id) is None