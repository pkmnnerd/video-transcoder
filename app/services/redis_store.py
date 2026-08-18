"""Redis-backed storage for job state shared between API and worker."""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from ..models.job import TranscodeJob

JOB_KEY = "transcode:job:{id}"
ABORT_KEY = "transcode:job:{id}:abort"


def job_key(job_id: str) -> str:
    return JOB_KEY.format(id=job_id)


def abort_key(job_id: str) -> str:
    return ABORT_KEY.format(id=job_id)


class JobStore:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def save(self, job: TranscodeJob) -> None:
        await self.redis.set(job_key(job.id), job.model_dump_json(), ex=86400)

    async def get(self, job_id: str) -> TranscodeJob | None:
        raw = await self.redis.get(job_key(job_id))
        if raw is None:
            return None
        return TranscodeJob.model_validate_json(raw)

    async def get_all(self) -> list[TranscodeJob]:
        keys = await self.redis.keys(job_key("*"))
        jobs: list[TranscodeJob] = []
        for key in keys:
            raw = await self.redis.get(key)
            if raw:
                try:
                    jobs.append(TranscodeJob.model_validate_json(raw))
                except Exception:
                    pass
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs

    async def update(self, job_id: str, **changes: Any) -> None:
        job = await self.get(job_id)
        if job is None:
            return
        for k, v in changes.items():
            setattr(job, k, v)
        await self.save(job)

    async def request_abort(self, job_id: str) -> bool:
        """Return True if an abort flag was newly set (job was still active)."""
        job = await self.get(job_id)
        if job is None or job.is_terminal:
            return False
        await self.redis.set(abort_key(job_id), "1", ex=3600)
        return True

    async def is_abort_requested(self, job_id: str) -> bool:
        return await self.redis.get(abort_key(job_id)) is not None

    async def clear_abort(self, job_id: str) -> None:
        await self.redis.delete(abort_key(job_id))

    async def delete(self, job_id: str) -> None:
        await self.redis.delete(job_key(job_id), abort_key(job_id))