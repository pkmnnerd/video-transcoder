"""FFmpeg wrapper: probe input, build command, run with progress + abort support."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from ..models.settings import TranscodeSettings

ProbeResult = dict


class AbortedError(Exception):
    pass


class FFmpegError(Exception):
    pass


TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")

H264_PRESETS = (
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
)

VIDEO_EXT = {
    "libx264": "mp4",
    "libx265": "mp4",
    "libvpx-vp9": "webm",
    "libsvtav1": "mp4",
}


@dataclass
class TranscodeResult:
    output_path: Path
    output_size: int
    duration: float | None = None


async def probe(path: str | Path) -> ProbeResult:
    """Return ffprobe JSON for an input file."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe failed: {stderr.decode(errors='replace')}")
    return json.loads(stdout)


def _video_stream(probe: ProbeResult) -> dict | None:
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "video":
            return stream
    return None


def _duration(probe: ProbeResult) -> float | None:
    fmt = probe.get("format", {})
    try:
        return float(fmt.get("duration") or 0.0) or None
    except (TypeError, ValueError):
        return None


def build_command(
    input_path: Path,
    output_path: Path,
    settings: TranscodeSettings,
) -> list[str]:
    """Build the ffmpeg argv list for the given settings."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-i", str(input_path)]

    vf: list[str] = []
    if settings.resolution:
        vf.append(f"scale={settings.resolution}")
    if settings.fps:
        vf.append(f"fps={settings.fps}")

    if vf:
        cmd += ["-vf", ",".join(vf)]

    # Global header for webm containers
    if VIDEO_EXT.get(settings.video_codec.value) == "webm":
        cmd += ["-deadline", "good", "-cpu-used", "4"]

    cmd += ["-c:v", settings.video_codec.value]

    if settings.video_codec.value in ("libx264", "libx265"):
        cmd += ["-preset", settings.preset, "-crf", str(settings.crf)]
    elif settings.video_codec.value == "libvpx-vp9":
        cmd += ["-crf", str(settings.crf), "-b:v", "0"]
    else:  # libsvtav1
        cmd += ["-crf", str(settings.crf), "-preset", "8"]

    if settings.audio_codec.value == "copy":
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", settings.audio_codec.value, "-b:a", settings.audio_bitrate]

    # Handle files with no audio stream gracefully
    cmd += ["-map", "0:v:0", "-map", "0:a:0?"]
    cmd += ["-movflags", "+faststart"]
    cmd += [str(output_path)]

    return cmd


async def transcode(
    input_path: Path,
    output_path: Path,
    settings: TranscodeSettings,
    progress_callback: Callable[[float], Awaitable[None]] | None = None,
    abort_check: Callable[[], Awaitable[bool]] | None = None,
) -> TranscodeResult:
    """Run ffmpeg with live progress reporting and cooperative abort.

    Progress is read from ``-progress pipe:1`` which emits newline-delimited
    ``key=value`` lines, avoiding the ``\\r``-separated stderr format.
    """
    total_duration = None
    try:
        probe_data = await probe(input_path)
        total_duration = _duration(probe_data)
    except FFmpegError:
        # Some odd files fail to probe; fall back to no percentage progress.
        pass

    cmd = build_command(input_path, output_path, settings)
    cmd = cmd[:2] + ["-nostats", "-progress", "pipe:1"] + cmd[2:]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    if proc.stdout is None or proc.stderr is None:
        raise FFmpegError("ffmpeg pipes unavailable")

    async def abort_requested() -> bool:
        if abort_check is None:
            return False
        try:
            return await abort_check()
        except Exception:
            return False

    async def terminate():
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        output_path.unlink(missing_ok=True)
        raise AbortedError()

    stderr_lines: list[str] = []

    async def read_stderr() -> None:
        async for line in proc.stderr:
            stderr_lines.append(line.decode(errors="replace"))

    stderr_task = asyncio.create_task(read_stderr())

    last_progress = 0.0
    try:
        while True:
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=1.0)
            except asyncio.TimeoutError:
                # No progress line within 1s: check abort, then keep waiting.
                if await abort_requested():
                    await terminate()
                continue

            if not line:
                break  # ffmpeg closed stdout -> process exiting

            text = line.decode(errors="replace").strip()
            if text.startswith("out_time="):
                m = TIME_RE.search(text)
                if m and total_duration:
                    h, mnt, sec = m.groups()
                    t = int(h) * 3600 + int(mnt) * 60 + float(sec)
                    pct = min(100.0, max(0.0, t / total_duration * 100))
                    if pct - last_progress >= 0.5:
                        last_progress = pct
                        if progress_callback:
                            await progress_callback(pct)
            elif text == "progress=end":
                pass

            if await abort_requested():
                await terminate()
    except AbortedError:
        raise

    retcode = await proc.wait()
    await stderr_task

    if retcode != 0:
        detail = "".join(stderr_lines)[-2000:]
        raise FFmpegError(f"ffmpeg exited with code {retcode}: {detail}")

    if not output_path.exists():
        raise FFmpegError("output file not produced")

    if progress_callback:
        await progress_callback(100.0)

    return TranscodeResult(
        output_path=output_path,
        output_size=output_path.stat().st_size,
        duration=total_duration,
    )