"""Tests for ffmpeg command building (no binary required)."""

from pathlib import Path

from app.models.settings import TranscodeSettings
from app.services.ffmpeg import build_command


def test_basic_h264_command():
    cmd = build_command(
        Path("/in/v.mp4"),
        Path("/out/o.mp4"),
        TranscodeSettings(video_codec="libx264", crf=23, preset="slow"),
    )
    assert cmd[0] == "ffmpeg"
    assert "-i" in cmd
    assert cmd[cmd.index("-i") + 1] == "/in/v.mp4"
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-crf") + 1] == "23"
    assert cmd[cmd.index("-preset") + 1] == "slow"
    assert cmd[-1] == "/out/o.mp4"


def test_resolution_and_fps_filter():
    cmd = build_command(
        Path("/in/v.mp4"),
        Path("/out/o.mp4"),
        TranscodeSettings(resolution="1280x720", fps=30),
    )
    i = cmd.index("-vf")
    assert cmd[i + 1] == "scale=1280x720,fps=30"


def test_vp9_webm_container():
    cmd = build_command(
        Path("/in/v.mp4"),
        Path("/out/o.webm"),
        TranscodeSettings(video_codec="libvpx-vp9", crf=30),
    )
    assert cmd[cmd.index("-c:v") + 1] == "libvpx-vp9"
    assert cmd[cmd.index("-crf") + 1] == "30"
    assert "-b:v" in cmd


def test_audio_copy_and_map():
    cmd = build_command(
        Path("/in/v.mp4"),
        Path("/out/o.mp4"),
        TranscodeSettings(audio_codec="copy"),
    )
    assert cmd[cmd.index("-c:a") + 1] == "copy"
    # optional audio map: -map 0:a:0?
    assert "-map" in cmd


def test_no_resolution_means_no_vf():
    cmd = build_command(
        Path("/in/v.mp4"),
        Path("/out/o.mp4"),
        TranscodeSettings(),
    )
    assert "-vf" not in cmd