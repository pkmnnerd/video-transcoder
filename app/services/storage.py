"""Filesystem helpers for uploads and outputs."""

from __future__ import annotations

import uuid
from pathlib import Path

import aiofiles


class StorageError(Exception):
    pass


class Storage:
    """Handles writing uploads and locating outputs on the local filesystem."""

    def __init__(self, upload_dir: Path, output_dir: Path) -> None:
        self.upload_dir = upload_dir
        self.output_dir = output_dir
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def input_path_for(self, job_id: str, filename: str) -> Path:
        safe_name = Path(filename).name  # strip any path traversal
        return self.upload_dir / f"{job_id}--{safe_name}"

    def output_path_for(self, job_id: str, container: str = "mp4") -> Path:
        return self.output_dir / f"{job_id}.{container}"

    async def save_upload(self, job_id: str, filename: str, data: bytes) -> Path:
        path = self.input_path_for(job_id, filename)
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)
        return path

    async def save_upload_stream(self, job_id: str, filename: str, upload) -> Path:
        """Stream a chunked upload to disk without buffering in memory."""
        path = self.input_path_for(job_id, filename)
        async with aiofiles.open(path, "wb") as f:
            while True:
                chunk = await upload.read(1 << 20)
                if not chunk:
                    break
                await f.write(chunk)
        return path

    def delete_files(self, job_id: str) -> None:
        for path in self.upload_dir.glob(f"{job_id}--*"):
            path.unlink(missing_ok=True)
        for path in self.output_dir.glob(f"{job_id}.*"):
            path.unlink(missing_ok=True)


def new_job_id() -> str:
    return uuid.uuid4().hex[:12]