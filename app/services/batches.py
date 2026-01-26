from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import fitz  # type: ignore import-not-found
from fastapi import UploadFile
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.enums import BatchStatus, DocumentStatus
from app.core.storage import batch_dir, ensure_base_dir, unique_filename
from app.models import Batch, Document

import subprocess
import shutil


def _documents_with_fields():
    return selectinload(Batch.documents).selectinload(Document.fields)

MAX_BATCH_TITLE_LENGTH = 120
_settings = get_settings()
logger = logging.getLogger(__name__)


def _normalize_batch_title(title: Optional[str]) -> Optional[str]:
    if not title:
        return None
    cleaned = title.strip()
    if not cleaned:
        return None
    if len(cleaned) > MAX_BATCH_TITLE_LENGTH:
        cleaned = cleaned[:MAX_BATCH_TITLE_LENGTH]
    return cleaned


def extract_batch_title(batch: Batch) -> Optional[str]:
    meta = batch.meta if isinstance(batch.meta, dict) else {}
    title = meta.get("title")
    if isinstance(title, str):
        cleaned = title.strip()
        return cleaned or None
    return None

def _is_docx(path: Path, content_type: Optional[str]) -> bool:
    if path.suffix.lower() == ".docx":
        return True
    if content_type:
        ctype = content_type.split(";", 1)[0].strip().lower()
        return ctype == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return False


def _is_xlsx(path: Path, content_type: Optional[str]) -> bool:
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        return True
    if content_type:
        ctype = content_type.split(";", 1)[0].strip().lower()
        return ctype in {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel.sheet.macroenabled.12",
        }
    return False


def _is_pdf(path: Path, content_type: Optional[str]) -> bool:
    if path.suffix.lower() == ".pdf":
        return True
    if content_type:
        return content_type.split(";", 1)[0].strip().lower() == "application/pdf"
    return False


def _find_soffice() -> Optional[str]:
    env_path = os.environ.get("SOFFICE_PATH")
    if env_path:
        candidate = Path(env_path)
        if candidate.exists():
            return str(candidate)

    for candidate in ("soffice", "soffice.exe", "soffice.com"):
        path = shutil.which(candidate)
        if path:
            return path

    try:
        result = subprocess.run(
            ["where", "soffice"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.lower().endswith(("soffice.exe", "soffice.com")) and Path(line).exists():
                return line
    except Exception:
        pass

    return None


def _convert_docx_to_pdf(source: Path, target_dir: Path, base_name: str, timeout_sec: int = 120) -> Optional[Path]:
    """
    Конвертирует DOCX в PDF в target_dir с помощью LibreOffice (`soffice --headless`).
    Возвращает путь к PDF или None при ошибке.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    soffice = _find_soffice()
    if not soffice:
        return None
    try:
        completed = subprocess.run(
            [
                soffice,
                "--headless", "--nologo", "--nodefault", "--nofirststartwizard",
                "--convert-to", "pdf",
                "--outdir", str(target_dir),
                str(source),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_sec,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    # Ожидаем имя {stem}.pdf
    candidate = target_dir / f"{Path(base_name).stem}.pdf"
    if candidate.exists():
        return candidate

    # Fallback: взять самый свежий PDF
    pdfs = sorted(target_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    return pdfs[0] if pdfs else None


def _convert_xlsx_to_pdf(source: Path, target_dir: Path, base_name: str, timeout_sec: int = 120) -> Optional[Path]:
    """
    Конвертирует XLSX/XLSM в PDF в target_dir с помощью LibreOffice (`soffice --headless`).
    Возвращает путь к PDF или None при ошибке.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    soffice = _find_soffice()
    if not soffice:
        return None
    try:
        subprocess.run(
            [
                soffice,
                "--headless",
                "--nologo",
                "--nodefault",
                "--nofirststartwizard",
                "--convert-to",
                "pdf",
                "--outdir",
                str(target_dir),
                str(source),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_sec,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    candidate = target_dir / f"{Path(base_name).stem}.pdf"
    if candidate.exists():
        return candidate

    pdfs = sorted(target_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    return pdfs[0] if pdfs else None

def _split_pdf_file(source: Path, target_dir: Path, base_name: str) -> List[Path]:
    try:
        document = fitz.open(source)  # type: ignore[misc]
    except Exception:
        return []

    try:
        if document.page_count <= 1:
            return []

        created: List[Path] = []
        base_stem = Path(base_name).stem
        suffix = Path(base_name).suffix or ".pdf"

        for index in range(document.page_count):
            single = fitz.open()  # type: ignore[misc]
            try:
                single.insert_pdf(document, from_page=index, to_page=index)
                candidate = unique_filename(target_dir, f"{base_stem}_p{index + 1}{suffix}")
                output_path = target_dir / candidate
                single.save(output_path)
                created.append(output_path)
            finally:
                single.close()
        return created
    finally:
        document.close()


def _generate_pdf_preview(pdf_path: Path, preview_dir: Path) -> None:
    try:
        document = fitz.open(pdf_path)  # type: ignore[misc]
    except Exception:
        return

    try:
        if document.page_count < 1:
            return
        page = document.load_page(0)
        rect = page.rect
        if rect.width <= 0 or rect.height <= 0:
            return
        scale = min(_settings.preview_max_width / rect.width, _settings.preview_max_height / rect.height)
        if scale <= 0:
            scale = 1.0
        matrix = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        preview_dir.mkdir(parents=True, exist_ok=True)
        for existing in preview_dir.glob("*.png"):
            existing.unlink(missing_ok=True)  # type: ignore[arg-type]
        pix.save(preview_dir / "page_1.png")
    except Exception:
        logger.debug("Failed to generate preview for %s", pdf_path, exc_info=True)
    finally:
        document.close()


async def create_batch(session: AsyncSession, created_by: Optional[str], title: Optional[str] = None) -> Batch:
    ensure_base_dir()
    batch = Batch(created_by=created_by)
    normalized_title = _normalize_batch_title(title)
    if normalized_title:
        meta = batch.meta if isinstance(batch.meta, dict) else {}
        batch.meta = {**meta, "title": normalized_title}
    meta = batch.meta if isinstance(batch.meta, dict) else {}
    batch.meta = {**meta, "prep_complete": False}
    session.add(batch)
    await session.flush()
    batch_paths = batch_dir(str(batch.id))
    batch_paths.ensure()
    return batch


async def get_batch(session: AsyncSession, batch_id: uuid.UUID) -> Optional[Batch]:
    stmt: Select = select(Batch).where(Batch.id == batch_id).options(_documents_with_fields())
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_batch_summaries(session: AsyncSession) -> Sequence[Batch]:
    stmt = select(Batch).options(selectinload(Batch.documents)).order_by(Batch.created_at.desc())
    result = await session.execute(stmt)
    return result.scalars().all()


async def save_documents(
    session: AsyncSession,
    batch: Batch,
    files: Iterable[UploadFile],
    *,
    update_status: bool = True,
) -> List[str]:
    batch_paths = batch_dir(str(batch.id))
    batch_paths.ensure()
    saved_urls: List[str] = []

    async def _add_document(path: Path, mime: Optional[str]) -> None:
        document = Document(
            batch_id=batch.id,
            filename=path.name,
            mime=mime,
            status=DocumentStatus.NEW,
        )
        session.add(document)
        await session.flush()
        if mime == "application/pdf":
            try:
                _generate_pdf_preview(path, batch_paths.preview_for(str(document.id)))
            except Exception:
                logger.debug("Preview generation failed for %s", path, exc_info=True)
        saved_urls.append(f"/files/batches/{batch.id}/raw/{path.name}")

    for upload in files:
        filename = upload.filename or "document"
        content_type = upload.content_type
        safe_name = unique_filename(batch_paths.raw, filename)
        dest = batch_paths.raw / safe_name

        with dest.open("wb") as buffer:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                buffer.write(chunk)
        await upload.close()

        created_paths: List[Path] = []
        pdf_source: Optional[Path] = None

        if _is_pdf(dest, content_type):
            pdf_source = dest
        elif _is_docx(dest, content_type):
            pdf_source = _convert_docx_to_pdf(dest, batch_paths.raw, safe_name)
        elif _is_xlsx(dest, content_type):
            pdf_source = _convert_xlsx_to_pdf(dest, batch_paths.raw, safe_name)

        if pdf_source and pdf_source.exists():
            created_paths = _split_pdf_file(pdf_source, batch_paths.raw, pdf_source.name)
            if created_paths:
                try:
                    dest.unlink()
                except FileNotFoundError:
                    pass
                if pdf_source != dest:
                    try:
                        pdf_source.unlink()
                    except FileNotFoundError:
                        pass
                for page_path in created_paths:
                    await _add_document(page_path, "application/pdf")
                continue

            if pdf_source != dest:
                try:
                    dest.unlink()
                except FileNotFoundError:
                    pass
            await _add_document(pdf_source, "application/pdf")
            continue

        await _add_document(dest, content_type)

    if saved_urls and update_status:
        batch.status = BatchStatus.PREPARED
        await session.flush()

    return saved_urls


async def compute_batch_counts(session: AsyncSession) -> dict:
    stmt = select(func.count(Batch.id))
    total_batches = (await session.execute(stmt)).scalar_one()
    stmt_docs = select(func.count(Document.id))
    total_docs = (await session.execute(stmt_docs)).scalar_one()
    return {"batches": total_batches, "documents": total_docs}
