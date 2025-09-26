from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.api.schemas import ArchiveEntry, ArchiveResponse
from app.core.storage import batch_dir
from app.services import batches as batch_service

router = APIRouter(tags=["archive"])


@router.get("/archive", response_model=ArchiveResponse)
async def list_batches(session: AsyncSession = Depends(get_db)) -> ArchiveResponse:
    batches = await batch_service.list_batch_summaries(session)
    items: List[ArchiveEntry] = []
    for batch in batches:
        report_file = batch_dir(str(batch.id)).report / "report.json"
        report_url = f"/files/batches/{batch.id}/report/report.json" if report_file.exists() else None
        items.append(
            ArchiveEntry(
                id=batch.id,
                status=batch.status,
                created_at=batch.created_at,
                updated_at=batch.updated_at,
                document_count=len(batch.documents),
                report_url=report_url,
            )
        )
    return ArchiveResponse(batches=items)
