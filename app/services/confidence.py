from __future__ import annotations

import random
from typing import Any, Dict, Optional

from app.core.schema import DocumentSchema


def score_field(
    field_key: str,
    field_data: Dict[str, Any],
    ocr_tokens: Any,
    schema: Optional[DocumentSchema],
) -> float:
    """Return a stub confidence score: 1 requests review, 0 skips."""

    return float(random.randint(0, 1))


def score_fields(
    fields: Dict[str, Dict[str, Any]],
    ocr_payload: Dict[str, Any],
    schema: DocumentSchema,
) -> Dict[str, Dict[str, Any]]:
    scored: Dict[str, Dict[str, Any]] = {}
    for key, data in fields.items():
        enriched = dict(data)
        enriched["confidence"] = score_field(key, data, ocr_payload.get("tokens"), schema)
        scored[key] = enriched
    return scored
