from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.core.config import get_settings


_settings = get_settings()

RAW_DIR = "raw"
DERIVED_DIR = "derived"
PREVIEW_DIR = "preview"
REPORT_DIR = "report"
FEEDBACK_DIR = "feedback"
FEEDBACK_PENDING_DIR = "pending"
FEEDBACK_SENT_DIR = "sent"
_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class BatchPaths:
    """Filesystem helpers for a single batch."""

    base: Path

    @property
    def raw(self) -> Path:
        return self.base / RAW_DIR

    @property
    def derived(self) -> Path:
        return self.base / DERIVED_DIR

    @property
    def preview(self) -> Path:
        return self.base / PREVIEW_DIR

    @property
    def report(self) -> Path:
        return self.base / REPORT_DIR

    def ensure(self) -> None:
        for path in (self.base, self.raw, self.derived, self.preview, self.report):
            path.mkdir(parents=True, exist_ok=True)

    def derived_for(self, doc_id: str) -> Path:
        path = self.derived / doc_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def preview_for(self, doc_id: str) -> Path:
        path = self.preview / doc_id
        path.mkdir(parents=True, exist_ok=True)
        return path


def ensure_base_dir() -> None:
    _settings.base_dir.mkdir(parents=True, exist_ok=True)
    batches_root().mkdir(parents=True, exist_ok=True)
    feedback_root().mkdir(parents=True, exist_ok=True)
    feedback_pending_root().mkdir(parents=True, exist_ok=True)
    feedback_sent_root().mkdir(parents=True, exist_ok=True)


def batches_root() -> Path:
    return _settings.base_dir / "batches"


def feedback_root() -> Path:
    return _settings.base_dir / FEEDBACK_DIR


def feedback_pending_root() -> Path:
    return feedback_root() / FEEDBACK_PENDING_DIR


def feedback_sent_root() -> Path:
    return feedback_root() / FEEDBACK_SENT_DIR


def batch_dir(batch_id: str) -> BatchPaths:
    base = batches_root() / batch_id
    return BatchPaths(base=base)


def list_batches() -> Iterable[Path]:
    root = batches_root()
    if not root.exists():
        return []
    return (p for p in root.iterdir() if p.is_dir())


def remove_batch(batch_id: str) -> None:
    path = batch_dir(batch_id).base
    if path.exists():
        shutil.rmtree(path)


def normalize_filename(name: str) -> str:
    """Return filesystem-safe basename preserving extension."""

    clean = Path(name).name
    stem = _FILENAME_SAFE.sub("_", Path(clean).stem)
    suffix = ''.join(Path(clean).suffixes)
    sanitized = stem or "file"
    return f"{sanitized}{suffix}"


def unique_filename(directory: Path, filename: str) -> str:
    """Ensure filename is unique within directory."""

    base = Path(normalize_filename(filename))
    candidate = base
    counter = 1
    while (directory / candidate.name).exists():
        candidate = Path(f"{base.stem}_{counter}{base.suffix}")
        counter += 1
    return candidate.name
