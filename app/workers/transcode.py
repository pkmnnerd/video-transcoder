"""arq worker: executes transcode jobs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from arq.connections import RedisSettings

from ..config import Settings
from ..models.job import JobStatus, TranscodeJob
from ..models.settings import TranscodeSettings
from ..services.ffmpeg import VIDEO_EXT, AbortedError, FFmpegError, transcode
from ..services.redis_store import JobStore

logger = logging.getLogger("transcode.worker")


async def startup(ctx) -> None:
    ctx["settings"] = Settings()
    ctx["store"] = JobStore(ctx["redis"])
    Path(ctx["settings"].upload_dir).mkdir(parents=True, exist_ok=True)
    Path(ctx["settings"].output_dir).mkdir(parents=True, exist_ok=True)


async def transcode_video(ctx, job_data: dict) -> dict:
    """Entry point invoked by arq for task name 'transcode_video'."""
    job = TranscodeJob.model_validate(job_data)
    store: JobStore = ctx["store"]
    settings: Settings = ctx["settings"]

    await store.update(job.id, status=JobStatus.RUNNING, started_at=datetime.now(timezone.utc))

    job_status = JobStatus.FAILED
    error: str | None = None
    output_path = None

    try:
        trans_settings = TranscodeSettings.model_validate(job.settings)
        container = VIDEO_EXT.get(trans_settings.video_codec.value, "mp4")
        out = Path(settings.output_dir) / f"{job.id}.{container}"

        async def progress(pct: float) -> None:
            await store.update(job.id, progress=pct)

        async def abort_check() -> bool:
            return await store.is_abort_requested(job.id)

        result = await transcode(
            Path(job.input_path),
            out,
            trans_settings,
            progress_callback=progress,
            abort_check=abort_check,
        )
        await store.update(
            job.id,
            status=JobStatus.COMPLETED,
            output_path=str(result.output_path),
            progress=100.0,
            completed_at=datetime.now(timezone.utc),
            duration=result.duration,
        )
        job_status = JobStatus.COMPLETED
        output_path = str(result.output_path)

    except AbortedError:
        job_status = JobStatus.ABORTED
        error = "aborted by user"
    except FFmpegError as exc:
        error = str(exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("unexpected error transcoding job %s", job.id)
        error = f"{type(exc).__name__}: {exc}"

    await store.update(job.id, status=job_status, error=error, output_path=output_path)
    await store.clear_abort(job.id)

    return {"job_id": job.id, "status": job_status, "output_path": output_path}


class WorkerSettings:
    functions = [transcode_video]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(Settings().redis_url)
    max_jobs = Settings().worker_concurrency
    job_timeout = 60 * 60 * 24  # 24h ceiling per job
    keep_result = 0
    max_tries = 1