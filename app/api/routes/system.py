from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.api.schemas import SystemStatusResponse
from app.services import status as status_service

router = APIRouter(tags=["system"])


@router.get("/system/status", response_model=SystemStatusResponse)
async def system_status(session: AsyncSession = Depends(get_db)) -> SystemStatusResponse:
    snapshot = await status_service.get_system_status(session)
    return SystemStatusResponse(**snapshot)
