from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import archive, batches, system, web
from app.core.config import get_settings
from app.core.storage import ensure_base_dir

settings = get_settings()
ensure_base_dir()

app = FastAPI(title=settings.app_name, debug=settings.debug)
app.mount("/files", StaticFiles(directory=settings.base_dir, html=False), name="files")

app.include_router(batches.router)
app.include_router(archive.router)
app.include_router(system.router)
app.include_router(web.router)


@app.get("/ping")
async def ping() -> dict:
    return {"status": "ok"}
