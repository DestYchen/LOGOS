from __future__ import annotations

import uuid
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import fitz  # type: ignore import-not-found
from fastapi import UploadFile
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import BatchStatus, DocumentStatus
from app.core.storage import batch_dir, ensure_base_dir, unique_filename
from app.models import Batch, Document

import subprocess


def _documents_with_fields():
    return selectinload(Batch.documents).selectinload(Document.fields)

def _is_docx(path: Path, content_type: Optional[str]) -> bool:
    if path.suffix.lower() == ".docx":
        return True
    if content_type:
        ctype = content_type.split(";", 1)[0].strip().lower()
        return ctype == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return False


def _is_pdf(path: Path, content_type: Optional[str]) -> bool:
    if path.suffix.lower() == ".pdf":
        return True
    if content_type:
        return content_type.split(";", 1)[0].strip().lower() == "application/pdf"
    return False

def _convert_docx_to_pdf(source: Path, target_dir: Path, base_name: str, timeout_sec: int = 120) -> Optional[Path]:
    """
    Конвертирует DOCX в PDF в target_dir с помощью LibreOffice (`soffice --headless`).
    Возвращает путь к PDF или None при ошибке.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            [
                "soffice",
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


async def create_batch(session: AsyncSession, created_by: Optional[str]) -> Batch:
    ensure_base_dir()
    batch = Batch(created_by=created_by)
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


async def save_documents(session: AsyncSession, batch: Batch, files: Iterable[UploadFile]) -> List[str]:
    batch_paths = batch_dir(str(batch.id))
    batch_paths.ensure()
    saved_urls: List[str] = []

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
        if _is_pdf(dest, content_type):
            created_paths = _split_pdf_file(dest, batch_paths.raw, safe_name)

        elif _is_docx(dest, content_type):
            # DOCX → PDF
            pdf_path = _convert_docx_to_pdf(dest, batch_paths.raw, safe_name)
            if pdf_path and pdf_path.exists():
                # PDF → страницы
                created_paths = _split_pdf_file(pdf_path, batch_paths.raw, pdf_path.name)

                if created_paths:
                    # Удаляем исходники, чтобы не плодить хранение
                    try:
                        dest.unlink()     # исходный .docx
                    except FileNotFoundError:
                        pass
                    try:
                        pdf_path.unlink() # общий .pdf
                    except FileNotFoundError:
                        pass
                else:
                    # Одностраничный PDF или ошибка разрезания → оставим исходный DOCX
                    try:
                        pdf_path.unlink()
                    except FileNotFoundError:
                        pass

        if created_paths:
            try:
                dest.unlink()
            except FileNotFoundError:
                pass

            for page_path in created_paths:
                document = Document(
                    batch_id=batch.id,
                    filename=page_path.name,
                    mime="application/pdf",
                    status=DocumentStatus.NEW,
                )
                session.add(document)
                saved_urls.append(f"/files/batches/{batch.id}/raw/{page_path.name}")
        else:
            document = Document(
                batch_id=batch.id,
                filename=safe_name,
                mime=content_type,
                status=DocumentStatus.NEW,
            )
            session.add(document)
            saved_urls.append(f"/files/batches/{batch.id}/raw/{safe_name}")

    if saved_urls:
        batch.status = BatchStatus.PREPARED
        await session.flush()

    return saved_urls


async def compute_batch_counts(session: AsyncSession) -> dict:
    stmt = select(func.count(Batch.id))
    total_batches = (await session.execute(stmt)).scalar_one()
    stmt_docs = select(func.count(Document.id))
    total_docs = (await session.execute(stmt_docs)).scalar_one()
    return {"batches": total_batches, "documents": total_docs}
