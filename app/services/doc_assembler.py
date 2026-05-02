from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List

import httpx

from app.core.config import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()


async def assemble_pages(batch_id: str, pages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not settings.doc_assembler_endpoint:
        return []

    payload = {"batch_id": batch_id, "pages": list(pages)}
    if not payload["pages"]:
        return []

    try:
        async with httpx.AsyncClient(timeout=float(settings.doc_assembler_timeout)) as client:
            response = await client.post(str(settings.doc_assembler_endpoint), json=payload)
            response.raise_for_status()
            data = response.json()
    except Exception:
        logger.warning("Document assembler request failed for batch %s", batch_id, exc_info=True)
        return []

    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(groups, list):
        logger.warning("Document assembler returned invalid payload for batch %s", batch_id)
        return []

    normalized: List[Dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        doc_ids = group.get("page_doc_ids")
        final_doc_type = group.get("final_doc_type")
        if not isinstance(doc_ids, list) or not doc_ids or not isinstance(final_doc_type, str):
            continue
        normalized.append(
            {
                "group_id": str(group.get("group_id") or f"group_{len(normalized) + 1}"),
                "final_doc_type": final_doc_type,
                "page_doc_ids": [str(item) for item in doc_ids if item],
                "confidence": group.get("confidence"),
                "reason": str(group.get("reason") or ""),
            }
        )
    return normalized
