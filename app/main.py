"""FastAPI application: UI, upload, job management, download, SSE progress."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from redis.asyncio import Redis

from .config import Settings, get_settings
from .models.job import JobStatus, TranscodeJob
from .models.settings import PRESETS, AudioCodec, VideoCodec, TranscodeSettings
from .services.ffmpeg import VIDEO_EXT, probe
from .services.queue import enqueue_transcode
from .services.redis_store import JobStore
from .services.storage import Storage

app = FastAPI(title="Video Transcoder")
settings = get_settings()

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

_storage = Storage(settings.upload_dir, settings.output_dir)


def get_redis() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def get_store() -> JobStore:
    return JobStore(get_redis())


SAFE_FILENAME_RE = re.compile(r"[^\w\-.\u4e00-\u9fff]")


def safe_filename(name: str) -> str:
    return SAFE_FILENAME_RE.sub("_", Path(name).name)


@app.on_event("startup")
async def on_startup() -> None:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.output_dir.mkdir(parents=True, exist_ok=True)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "codecs": VideoCodec,
            "audio_codecs": AudioCodec,
            "presets": PRESETS,
            "settings": settings,
        },
    )


@app.post("/jobs")
async def create_job(
    request: Request,
    file: UploadFile = File(...),
    video_codec: str = Form("libx264"),
    crf: int = Form(23),
    preset: str = Form("medium"),
    resolution: str = Form(""),
    fps: int | None = Form(None),
    audio_codec: str = Form("copy"),
    audio_bitrate: str = Form("128k"),
):
    if file.filename is None or not file.filename.strip():
        raise HTTPException(status_code=400, detail="no file provided")

    original = safe_filename(file.filename)
    ext = Path(original).suffix.lower()
    if ext not in settings.allowed_extensions:
        raise HTTPException(status_code=415, detail=f"unsupported file type: {ext}")

    try:
        trans_settings = TranscodeSettings(
            video_codec=video_codec,
            crf=crf,
            preset=preset,
            resolution=resolution or None,
            fps=fps,
            audio_codec=audio_codec,
            audio_bitrate=audio_bitrate,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    job = TranscodeJob(original_filename=original)
    input_path = await _storage.save_upload_stream(job.id, original, file)

    job.input_path = str(input_path)
    job.settings = trans_settings.model_dump()

    store = get_store()
    await store.save(job)
    await enqueue_transcode(settings, job)

    if request.headers.get("hx-request"):
        return templates.TemplateResponse(request, "partials/job_card.html", {"job": job})
    return RedirectResponse(url=f"/job/{job.id}", status_code=303)


@app.get("/jobs")
async def list_jobs(request: Request):
    store = get_store()
    jobs = await store.get_all()
    return templates.TemplateResponse(request, "partials/job_list.html", {"jobs": jobs})


@app.get("/job/{job_id}")
async def job_page(request: Request, job_id: str):
    store = get_store()
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return templates.TemplateResponse(
        request,
        "job.html",
        {"job": job, "codecs": VideoCodec, "settings": settings},
    )


@app.get("/job/{job_id}/progress")
async def job_progress_sse(request: Request, job_id: str):
    store = get_store()

    async def event_stream():
        while True:
            if await request.is_disconnected():
                break
            job = await store.get(job_id)
            if job is None:
                yield "data: {\"status\": \"gone\"}\n\n"
                break
            payload = {
                "id": job.id,
                "status": job.status.value,
                "progress": job.progress,
                "error": job.error,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            if job.is_terminal:
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.delete("/job/{job_id}")
async def abort_job(job_id: str):
    store = get_store()
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.is_terminal:
        raise HTTPException(status_code=409, detail="job already finished")
    await store.request_abort(job_id)
    return {"status": "abort requested"}


@app.delete("/job/{job_id}/delete")
async def delete_job(job_id: str):
    store = get_store()
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.is_active:
        await store.request_abort(job_id)
    await asyncio.sleep(1)
    _storage.delete_files(job_id)
    await store.delete(job_id)
    return {"status": "deleted"}


@app.get("/job/{job_id}/download")
async def download_job(job_id: str):
    store = get_store()
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status != JobStatus.COMPLETED or not job.output_path:
        raise HTTPException(status_code=409, detail="output not ready")
    output = Path(job.output_path)
    if not output.exists():
        raise HTTPException(status_code=404, detail="output file missing")
    return FileResponse(
        output,
        filename=job.original_filename,
        media_type="application/octet-stream",
    )


@app.get("/job/{job_id}/info")
async def job_info(job_id: str):
    """Debug: raw probe info for the uploaded file."""
    store = get_store()
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    try:
        return await probe(job.input_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc