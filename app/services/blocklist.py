from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable, List, Pattern

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _read_patterns(path: Path) -> List[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except Exception:
        logger.warning("Failed to read blocklist patterns from %s", path, exc_info=True)
        return []

    patterns: List[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)
    return patterns


def _compile_patterns(raw: Iterable[str], *, case_sensitive: bool) -> List[Pattern[str]]:
    flags = 0 if case_sensitive else re.IGNORECASE
    compiled: List[Pattern[str]] = []
    for pattern in raw:
        if not pattern:
            continue
        try:
            compiled.append(re.compile(pattern, flags))
        except re.error:
            logger.warning("Invalid blocklist regex skipped: %s", pattern)
    return compiled


def load_patterns() -> List[Pattern[str]]:
    settings = get_settings()
    path = settings.blocked_doc_patterns_path
    if not path:
        return []
    raw = _read_patterns(path)
    return _compile_patterns(raw, case_sensitive=settings.blocked_doc_patterns_case_sensitive)


def should_drop(text: str) -> bool:
    if not text:
        return False
    for pattern in load_patterns():
        if pattern.search(text):
            return True
    return False
