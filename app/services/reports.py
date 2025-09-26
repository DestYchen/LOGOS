from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict

from app.core.storage import batch_dir


def report_path(batch_id: uuid.UUID) -> Path:
    return batch_dir(str(batch_id)).report / "report.json"


def load_report(batch_id: uuid.UUID) -> Dict[str, Any]:
    path = report_path(batch_id)
    if not path.exists():
        raise FileNotFoundError
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
