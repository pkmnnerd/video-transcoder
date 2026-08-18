# Detailed Implementation Plan: Local Video Transcoder

## Project Structure

```
/home/brian/video-transcoder/
├── docker-compose.yml          # Redis + app services
├── Dockerfile                  # App container
├── requirements.txt            # Python deps
├── pyproject.toml              # Project config
├── README.md
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app + routes
│   ├── config.py               # Settings (pydantic-settings)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── job.py              # Job Pydantic models
│   │   └── settings.py         # Transcode settings model
│   ├── services/
│   │   ├── __init__.py
│   │   ├── ffmpeg.py           # FFmpeg wrapper + progress parsing
│   │   ├── storage.py          # File I/O (upload/output paths)
│   │   └── queue.py            # arq job enqueueing
│   ├── workers/
│   │   ├── __init__.py
│   │   └── transcode.py        # arq worker function
│   ├── templates/
│   │   ├── base.html           # Base template
│   │   ├── index.html          # Upload form + job list
│   │   └── partials/
│   │       ├── job_card.html   # HTMX partial: job status
│   │       ├── progress_bar.html
│   │       └── settings_form.html
│   └── static/
│       ├── style.css           # Tailwind (compiled) or custom CSS
│       └── app.js              # Minimal JS (SSE/polling)
├── data/
│   ├── uploads/                # Input files
│   └── outputs/                # Transcoded files
└── tests/
    ├── __init__.py
    ├── test_ffmpeg.py
    ├── test_api.py
    └── test_worker.py
```

---

## Core Components Detail

### 1. Configuration (`app/config.py`)

```python
class Settings(BaseSettings):
    redis_url: str = "redis://localhost:6379/0"
    upload_dir: Path = Path("/data/uploads")
    output_dir: Path = Path("/data/outputs")
    max_file_size: int = 2_000_000_000  # 2GB
    allowed_extensions: set[str] = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv"}
    worker_concurrency: int = 1
    job_ttl_hours: int = 24
```

### 2. Job Model (`app/models/job.py`)

```python
class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"

class TranscodeJob(BaseModel):
    id: str  # UUID
    status: JobStatus = JobStatus.PENDING
    input_path: Path
    output_path: Path | None = None
    settings: TranscodeSettings
    progress: float = 0.0  # 0-100
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    file_size: int | None = None
    duration: float | None = None  # output duration
```

### 3. Transcode Settings (`app/models/settings.py`)

```python
class VideoCodec(str, Enum):
    H264 = "libx264"
    H265 = "libx265"
    VP9 = "libvpx-vp9"
    AV1 = "libsvtav1"

class AudioCodec(str, Enum):
    COPY = "copy"
    AAC = "aac"
    OPUS = "libopus"

class TranscodeSettings(BaseModel):
    video_codec: VideoCodec = VideoCodec.H264
    crf: int = 23  # 18-28
    preset: str = "medium"  # ultrafast..veryslow
    resolution: str | None = None  # "1920x1080" or None = keep original
    fps: int | None = None
    audio_codec: AudioCodec = AudioCodec.COPY
    audio_bitrate: str = "128k"
    hardware_accel: bool = False  # vaapi/nvenc/qsv
```

### 4. FFmpeg Service (`app/services/ffmpeg.py`)

Key responsibilities:
- Build ffmpeg command from `TranscodeSettings`
- Probe input (duration, resolution, codecs) via `ffprobe`
- Execute ffmpeg with `asyncio.create_subprocess_exec`
- Parse progress from stderr (time=, speed=, bitrate=)
- Support abort via `process.terminate()` + `process.wait()`
- Return output file metadata

```python
async def transcode(
    input_path: Path,
    output_path: Path,
    settings: TranscodeSettings,
    progress_callback: Callable[[float], None],
    abort_check: Callable[[], bool],
) -> TranscodeResult:
    # 1. ffprobe for duration
    # 2. Build -filter:v scale/fps, -c:v, -crf, -preset, -c:a, -b:a
    # 3. Run ffmpeg, parse stderr for time=XXX → progress %
    # 4. Check abort_check() each iteration
    # 5. On abort: terminate, cleanup partial file, raise AbortedError
```

### 5. Queue Service (`app/services/queue.py`)

Using `arq` (async Redis queue):

```python
# Enqueue
async def enqueue_transcode(job: TranscodeJob) -> str:
    await redis.enqueue_job("transcode_video", job.model_dump())
    return job.id

# Worker function (registered in arq)
async def transcode_video(ctx, job_data: dict) -> dict:
    job = TranscodeJob(**job_data)
    # Update status → RUNNING
    # Run ffmpeg.transcode with progress callback updating Redis
    # On success: status → COMPLETED, save output_path
    # On abort: status → ABORTED
    # On error: status → FAILED, save error
    return {"status": job.status, "output_path": str(job.output_path)}
```

### 6. API Routes (`app/main.py`)

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Render index.html (form + job list) |
| `/jobs` | POST | Create job: save upload, validate, enqueue, return job_id |
| `/jobs` | GET | List all jobs (HTMX partial for polling) |
| `/jobs/{id}` | GET | Job detail + SSE progress stream |
| `/jobs/{id}/progress` | GET | SSE endpoint: `data: {"progress": 45, "status": "running"}` |
| `/jobs/{id}` | DELETE | Abort job: set Redis flag, worker checks & terminates |
| `/jobs/{id}/download` | GET | FileResponse for output file |
| `/jobs/{id}/delete` | DELETE | Remove job + files (cleanup) |

### 7. Frontend (HTMX + Tailwind)

**index.html** - Single page with:
- Upload dropzone + settings form (collapsible advanced)
- Job list table: filename, status, progress bar, actions (abort/download/delete)
- HTMX polling: `hx-get="/jobs" hx-trigger="every 2s" hx-swap="outerHTML"`
- SSE for active job: `hx-ext="sse" sse-connect="/jobs/{id}/progress"`

**Progress updates via SSE**:
```html
<div id="job-{id}" hx-ext="sse" sse-connect="/jobs/{id}/progress">
  <div class="progress-bar" style="width: {progress}%"></div>
  <span>{status}</span>
</div>
```

---

## Docker Compose

```yaml
services:
  redis:
    image: redis:7-alpine
    volumes: [redis_data:/data]
    healthcheck: ["redis-cli", "ping"]

  app:
    build: .
    ports: ["8080:8080"]
    volumes:
      - ./data:/data
      - ./app:/app/app  # dev hot-reload
    environment:
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      redis:
        condition: service_healthy

  worker:
    build: .
    command: arq app.workers.transcode.WorkerSettings
    volumes:
      - ./data:/data
      - ./app:/app/app
    environment:
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      redis:
        condition: service_healthy
    deploy:
      resources:
        limits:
          cpus: "2"
          memory: "2G"

volumes:
  redis_data:
```

---

## Key Implementation Details

### Abort Flow
1. User clicks "Abort" → `DELETE /jobs/{id}`
2. API sets `job:{id}:abort = "1"` in Redis (TTL 5min)
3. Worker checks `await redis.get(f"job:{job_id}:abort")` every progress tick
4. If set: `process.terminate()`, cleanup, mark `ABORTED`

### Progress Parsing
```python
# ffmpeg stderr line: frame= 1234 fps= 30 q=28.0 size=  1024kB time=00:00:41.13 bitrate= 204.8kbits/s speed=1.2x
pattern = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
# progress = current_time / total_duration * 100
```

### Hardware Acceleration (optional)
- Detect via `ffmpeg -hwaccels` (vaapi, nvenc, qsv)
- Add `-hwaccel vaapi -vaapi_device /dev/dri/renderD128`
- Map: `h264`→`h264_vaapi`, `hevc`→`hevc_vaapi`

### File Cleanup
- Background task: delete jobs older than `JOB_TTL_HOURS`
- On abort/fail: delete partial output file

---

## Dependencies (`requirements.txt`)

```
fastapi==0.111.0
uvicorn[standard]==0.30.0
arq==0.23.0
redis==5.0.0
pydantic==2.7.0
pydantic-settings==2.3.0
python-multipart==0.0.9
jinja2==3.1.4
aiofiles==23.2.0
ffmpeg-python==0.2.0  # only for probe, not execution
pytest==8.2.0
pytest-asyncio==0.23.0
httpx==0.27.0
```

---

## Development Workflow

```bash
# Start
docker compose up --build -d

# Logs
docker compose logs -f app worker

# Test upload
curl -F "file=@test.mp4" -F "crf=23" http://localhost:8080/jobs

# Stop
docker compose down -v
```

---

## Open Questions for You

1. **Hardware acceleration**: Do you have Intel QuickSync (vaapi), NVIDIA (nvenc), or AMD (vaapi)? I can add auto-detection.
2. **Concurrency**: `worker_concurrency: 1` is safe for homelab. Increase if you have CPU/GPU headroom?
3. **Input validation**: Should I add a "preview" step (ffprobe info shown before queue)?
4. **Notifications**: Want desktop notification (via `notify-send`) or webhook on completion?
5. **Tailwind**: Use CDN (dev) or compile (prod)? CDN is simpler for homelab.

---

## Implementation Status

**All core functionality is implemented and verified end-to-end in Docker:**

- Upload (streaming) → transcode (background) → live progress → download → abort
- Verified paths: H.264→MP4, VP9→WebM (audio: copy / AAC / Opus), resolution scaling, abort
- 15 unit tests passing (`pytest`)

### Final file structure (differences from the original plan)

```
video-transcoder/
├── docker-compose.yml          # redis + app + worker (+ PYTHONDONTWRITEBYTECODE=1)
├── Dockerfile                  # python:3.12-slim + ffmpeg
├── requirements.txt            # pinned deps (fastapi, uvicorn, arq, redis, pydantic...)
├── pyproject.toml              # pytest config
├── README.md                   # setup + API + config docs
├── PLAN.md
├── app/
│   ├── main.py                 # FastAPI: UI, upload, jobs, SSE, abort, download, delete
│   ├── config.py               # pydantic-settings, prefix VIDEO_, project-relative ./data
│   ├── models/
│   │   ├── job.py              # TranscodeJob + JobStatus enum
│   │   └── settings.py         # TranscodeSettings + validators, PRESETS
│   ├── services/
│   │   ├── ffmpeg.py           # probe(), build_command(), transcode() w/ progress + abort
│   │   ├── redis_store.py      # JobStore: Redis-backed job state + abort flag  ← NEW
│   │   ├── storage.py          # streaming upload, safe filenames, cleanup
│   │   └── queue.py            # arq enqueue (create_pool + RedisSettings)
│   ├── workers/transcode.py    # arq WorkerSettings + transcode_video task
│   ├── templates/
│   │   ├── base.html           # htmx + htmx-sse CDN
│   │   ├── index.html          # upload form + auto-polling job list
│   │   ├── job.html            # single-job page
│   │   └── partials/
│   │       ├── job_list.html
│   │       └── job_card.html   # progress bar, abort/download/delete buttons
│   ├── static/
│   │   ├── style.css           # dark theme (no Tailwind dependency)
│   │   └── app.js              # SSE progress wiring  ← NEW
├── data/uploads|outputs/       # local storage
└── tests/                      # test_settings, test_ffmpeg, test_redis_store
```

### Deviations from the original plan (and why)

1. **Progress parsing uses `-progress pipe:1`, not stderr regex.**
   ffmpeg writes status to stderr with `\r` (no newlines), so line-based reads never
   yield while running — progress stayed at 0 and abort never fired. The fix adds
   `-nostats -progress pipe:1`, which emits newline-delimited `key=value` lines
   (`out_time=...`, `progress=end`). stdout is read line-by-line; stderr is drained
   separately only to capture the error message on failure. Abort is checked on every
   progress line and on a 1s idle timeout (see `app/services/ffmpeg.py:transcode`).

2. **SSE is wired through `app/static/app.js`, not the htmx-sse swap.**
   htmx-sse `sse-swap="message"` replaces a node with the raw message body, which is
   JSON here — so the card would be clobbered. `app.js` opens an `EventSource` per
   active card, updates the progress bar/badge in place, and re-fetches `/jobs` when a
   job reaches a terminal state (to swap in download/delete buttons).

3. **Config defaults are project-relative (`./data/...`).** `VIDEO_UPLOAD_DIR` /
   `VIDEO_OUTPUT_DIR` default to `PROJECT_ROOT/data/...` so it runs without root;
   the Docker compose overrides them to `/data/...`.

4. **Upload streaming uses `UploadFile.read()`, not `.chunks()`.**
   Starlette 0.37's `UploadFile` has no `.chunks()` method, so the storage layer loops
   on `await upload.read(1 << 20)`.

5. **arq 0.25 API:** `create_pool()` takes a `RedisSettings`, not an `ArqRedis`
   instance (`create_pool(RedisSettings.from_dsn(...))`).

6. **`PYTHONDONTWRITEBYTECODE=1`** on both services: the container runs as root and
   was writing root-owned `__pycache__` into the `./app` volume mount, which then
   blocked host-side cleanup/compilation.

7. **No Tailwind.** A small custom `style.css` (dark theme) avoids a build step and
   CDN dependency — more appropriate for a homelab.

8. **Tests added** for settings validation, ffmpeg command building, and JobStore
   (via `fakeredis`).

### Verified end-to-end results

| Scenario | Result |
|----------|--------|
| libx264 + scale + copy audio → MP4 | completed, download OK |
| libvpx-vp9 + libopus → WebM | completed, download OK |
| Abort (veryslow encode) | aborted in ~5s, partial file removed |
| Job page / list / SSE | renders + live progress |
| Unsupported extension / bad preset | 415 / 422 errors |
| Worker restart during job | arq marks job retries-exceeded (expected) |