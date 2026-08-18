# Local Video Transcoder

Self-hosted single-user web app for transcoding videos with ffmpeg. Upload a file, pick codec/quality/resolution, and download the result. Jobs run in the background and can be aborted.

## Features

- Web UI (HTMX + SSE): upload, settings, live progress, download, abort
- Codecs: H.264, H.265, VP9, AV1
- CRF quality, encoder preset, resolution scale, FPS, audio codec/bitrate
- Background worker via arq + Redis
- Abort in-progress jobs (SIGTERM to ffmpeg)

## Quick start

```bash
docker compose up --build -d
```

Open http://localhost:8080

## Manual / non-Docker

Requires Python 3.12+ and ffmpeg on PATH.

```bash
pip install -r requirements.txt

# terminal 1: worker
arq app.workers.transcode.WorkerSettings

# terminal 2: web app
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Configuration (env vars, prefix `VIDEO_`)

| Var | Default | Notes |
|-----|---------|-------|
| `VIDEO_REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `VIDEO_UPLOAD_DIR` | `/data/uploads` | Input files |
| `VIDEO_OUTPUT_DIR` | `/data/outputs` | Transcoded files |
| `VIDEO_MAX_FILE_SIZE` | `4294967296` | 4 GiB |
| `VIDEO_WORKER_CONCURRENCY` | `1` | Parallel jobs |
| `VIDEO_JOB_TTL_HOURS` | `24` | Job retention |

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | UI |
| POST | `/jobs` | Create job (multipart: `file` + form fields) |
| GET | `/jobs` | List jobs (HTML partial) |
| GET | `/job/{id}` | Job page |
| GET | `/job/{id}/progress` | SSE progress stream |
| DELETE | `/job/{id}` | Abort job |
| GET | `/job/{id}/download` | Download output |
| DELETE | `/job/{id}/delete` | Delete job + files |

### POST /jobs form fields

- `video_codec`: `libx264` \| `libx265` \| `libvpx-vp9` \| `libsvtav1`
- `crf`: 0–51 (lower = higher quality)
- `preset`: `ultrafast`…`veryslow`
- `resolution`: `""` (original) or `WxH` e.g. `1920x1080`
- `fps`: optional int
- `audio_codec`: `copy` \| `aac` \| `libopus`
- `audio_bitrate`: e.g. `128k`

## Abort flow

`DELETE /job/{id}` sets an abort flag in Redis. The worker polls it on each progress tick (~0.5s) and terminates the ffmpeg process, removing the partial output.

## Hardware acceleration

Not enabled by default. Set `VIDEO_HARDWARE_ACCEL=true` and adjust the codec mapping in `app/services/ffmpeg.py` to your GPU (vaapi/nvenc/qsv).