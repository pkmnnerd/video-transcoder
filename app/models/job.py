"""Transcoding job model."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class TranscodeJob(BaseModel):
    """A single transcoding job stored in Redis."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: JobStatus = JobStatus.PENDING
    original_filename: str
    input_path: str = ""
    output_path: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    progress: float = 0.0
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration: float | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.ABORTED,
        )

    @property
    def is_active(self) -> bool:
        return self.status in (JobStatus.PENDING, JobStatus.RUNNING)