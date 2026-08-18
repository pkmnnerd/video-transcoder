"""Transcoding settings model + validation."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class VideoCodec(str, Enum):
    H264 = "libx264"
    H265 = "libx265"
    VP9 = "libvpx-vp9"
    AV1 = "libsvtav1"


class AudioCodec(str, Enum):
    COPY = "copy"
    AAC = "aac"
    OPUS = "libopus"


PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow")


class TranscodeSettings(BaseModel):
    video_codec: VideoCodec = VideoCodec.H264
    crf: int = Field(default=23, ge=0, le=51)
    preset: str = "medium"
    resolution: str | None = None  # "1920x1080" or None = keep original
    fps: int | None = Field(default=None, ge=1, le=120)
    audio_codec: AudioCodec = AudioCodec.COPY
    audio_bitrate: str = "128k"

    @field_validator("preset")
    @classmethod
    def validate_preset(cls, v: str) -> str:
        if v not in PRESETS:
            raise ValueError(f"preset must be one of {PRESETS}")
        return v

    @field_validator("resolution")
    @classmethod
    def validate_resolution(cls, v: str | None) -> str | None:
        if v is None or v.lower() in ("original", "keep", ""):
            return None
        if v.count("x") != 1:
            raise ValueError('resolution must be "WxH" (e.g. "1920x1080") or "original"')
        w, h = v.split("x")
        if not (w.isdigit() and h.isdigit()) or not (0 < int(w) <= 7680 and 0 < int(h) <= 4320):
            raise ValueError("resolution dimensions out of range")
        return f"{int(w)}x{int(h)}"

    @field_validator("audio_bitrate")
    @classmethod
    def validate_bitrate(cls, v: str) -> str:
        v = v.strip().lower()
        if v.endswith("k") and v[:-1].isdigit():
            return v
        raise ValueError('audio bitrate must be like "128k"')