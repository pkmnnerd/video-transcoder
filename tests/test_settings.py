"""Tests for transcode settings validation."""

import pytest
from pydantic import ValidationError

from app.models.settings import TranscodeSettings


def test_defaults():
    s = TranscodeSettings()
    assert s.video_codec.value == "libx264"
    assert s.crf == 23
    assert s.preset == "medium"
    assert s.resolution is None
    assert s.audio_codec.value == "copy"


def test_invalid_preset():
    with pytest.raises(ValidationError):
        TranscodeSettings(preset="turbo")


def test_resolution_validation():
    assert TranscodeSettings(resolution="1920x1080").resolution == "1920x1080"
    assert TranscodeSettings(resolution="original").resolution is None
    assert TranscodeSettings(resolution="").resolution is None
    with pytest.raises(ValidationError):
        TranscodeSettings(resolution="1920x1080x30")
    with pytest.raises(ValidationError):
        TranscodeSettings(resolution="abc")


def test_audio_bitrate():
    assert TranscodeSettings(audio_bitrate="192k").audio_bitrate == "192k"
    with pytest.raises(ValidationError):
        TranscodeSettings(audio_bitrate="abc")