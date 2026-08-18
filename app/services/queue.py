"""arq queue wrapper for enqueueing transcode jobs."""

from __future__ import annotations

from arq import create_pool
from arq.connections import RedisSettings

from ..config import Settings
from ..models.job import TranscodeJob

TASK_NAME = "transcode_video"


async def enqueue_transcode(settings: Settings, job: TranscodeJob) -> None:
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        await redis.enqueue_job(TASK_NAME, job.model_dump(mode="json"))
    finally:
        await redis.aclose()