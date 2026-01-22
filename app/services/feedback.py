from __future__ import annotations

import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import UploadFile

from app.core.config import get_settings
from app.core.storage import ensure_base_dir, feedback_pending_root, normalize_filename, unique_filename

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN_OVERRIDE = "8576804170:AAFPr5Tzjpe9mzSgBu8WgxkJQr_O_gPeqwM"
TELEGRAM_CHAT_ID_OVERRIDE = "-5216421758"
MAX_FEEDBACK_FILES = 5
MAX_FEEDBACK_FILE_MB = 5
MAX_FEEDBACK_FILE_BYTES = MAX_FEEDBACK_FILE_MB * 1024 * 1024
MAX_SUBJECT_LENGTH = 120
MAX_MESSAGE_LENGTH = 3500
MAX_CONTACT_LENGTH = 80
CHUNK_SIZE = 1024 * 1024

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg"}
ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
ALLOWED_FEEDBACK_TYPES = {"problem", "improvement"}
FEEDBACK_TYPE_LABELS = {
    "problem": "Проблема",
    "improvement": "Предложение по улучшению",
}


class FeedbackValidationError(ValueError):
    pass


def _normalize_text(value: str | None, *, max_len: int, field: str) -> str:
    if not value:
        raise FeedbackValidationError(f"{field}_required")
    cleaned = value.strip()
    if not cleaned:
        raise FeedbackValidationError(f"{field}_required")
    if len(cleaned) > max_len:
        raise FeedbackValidationError(f"{field}_too_long")
    return cleaned


def _normalize_optional_text(value: str | None, *, max_len: int, field: str) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_len:
        raise FeedbackValidationError(f"{field}_too_long")
    return cleaned


def _normalize_feedback_type(value: str | None) -> str:
    cleaned = (value or "").strip().lower()
    if not cleaned:
        return "problem"
    if cleaned not in ALLOWED_FEEDBACK_TYPES:
        raise FeedbackValidationError("feedback_type_invalid")
    return cleaned


def _is_allowed_image(upload: UploadFile) -> bool:
    content_type = (upload.content_type or "").lower()
    if content_type in ALLOWED_IMAGE_TYPES:
        return True
    name = normalize_filename(upload.filename or "")
    return Path(name).suffix.lower() in ALLOWED_IMAGE_EXTS


async def _save_upload_file(upload: UploadFile, target_dir: Path) -> Tuple[Dict[str, Any], Path]:
    if not _is_allowed_image(upload):
        await upload.close()
        raise FeedbackValidationError("unsupported_file_type")

    filename = upload.filename or "image"
    safe_name = unique_filename(target_dir, filename)
    file_path = target_dir / safe_name
    size = 0

    try:
        with file_path.open("wb") as buffer:
            while True:
                chunk = await upload.read(CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FEEDBACK_FILE_BYTES:
                    raise FeedbackValidationError("file_too_large")
                buffer.write(chunk)
    finally:
        await upload.close()

    content_type = upload.content_type or ""
    info = {
        "original_name": filename,
        "stored_name": safe_name,
        "content_type": content_type,
        "size": size,
    }
    return info, file_path


def _parse_context(raw: Optional[str]) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def _format_message(payload: Dict[str, Any]) -> str:
    subject = payload.get("subject") or "-"
    message = payload.get("message") or "-"
    ticket_id = payload.get("ticket_id") or "-"
    created_at = payload.get("created_at") or "-"
    feedback_type = payload.get("feedback_type") or "problem"
    contact = payload.get("contact")
    context = payload.get("context")
    type_label = FEEDBACK_TYPE_LABELS.get(str(feedback_type), str(feedback_type))
    lines = [
        f"Feedback #{ticket_id}",
        f"Type: {type_label}",
        f"Subject: {subject}",
        f"Created: {created_at}",
        "",
        "Message:",
        message,
    ]
    if contact:
        lines.insert(3, f"Contact: {contact}")
    if context:
        lines.append("")
        lines.append(f"Context: {json.dumps(context, ensure_ascii=False)}")
    return "\n".join(lines)


async def store_feedback(
    subject: str,
    message: str,
    feedback_type: Optional[str],
    contact: Optional[str],
    context_raw: Optional[str],
    files: List[UploadFile],
    *,
    meta: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Path, Dict[str, Any], List[Path]]:
    normalized_subject = _normalize_text(subject, max_len=MAX_SUBJECT_LENGTH, field="subject")
    normalized_message = _normalize_text(message, max_len=MAX_MESSAGE_LENGTH, field="message")
    normalized_type = _normalize_feedback_type(feedback_type)
    normalized_contact = _normalize_optional_text(contact, max_len=MAX_CONTACT_LENGTH, field="contact")

    if len(files) > MAX_FEEDBACK_FILES:
        raise FeedbackValidationError("too_many_files")

    ensure_base_dir()
    ticket_id = uuid.uuid4().hex
    ticket_dir = feedback_pending_root() / ticket_id
    files_dir = ticket_dir / "files"
    ticket_dir.mkdir(parents=True, exist_ok=True)
    files_dir.mkdir(parents=True, exist_ok=True)

    saved_files: List[Path] = []
    saved_info: List[Dict[str, Any]] = []

    try:
        for upload in files:
            info, path = await _save_upload_file(upload, files_dir)
            saved_files.append(path)
            saved_info.append(info)
    except Exception:
        shutil.rmtree(ticket_dir, ignore_errors=True)
        raise

    payload: Dict[str, Any] = {
        "ticket_id": ticket_id,
        "subject": normalized_subject,
        "message": normalized_message,
        "feedback_type": normalized_type,
        "contact": normalized_contact,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "context": _parse_context(context_raw),
        "files": saved_info,
        "meta": meta or {},
    }
    payload_path = ticket_dir / "payload.json"
    try:
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        shutil.rmtree(ticket_dir, ignore_errors=True)
        raise

    return ticket_id, ticket_dir, payload, saved_files


def cleanup_feedback(ticket_dir: Path) -> None:
    shutil.rmtree(ticket_dir, ignore_errors=True)


async def send_to_telegram(payload: Dict[str, Any], file_paths: List[Path]) -> bool:
    settings = get_settings()
    token = TELEGRAM_BOT_TOKEN_OVERRIDE or settings.telegram_bot_token
    chat_id = TELEGRAM_CHAT_ID_OVERRIDE or settings.telegram_chat_id
    if not token or not chat_id:
        logger.warning("Telegram feedback is disabled: missing token or chat id.")
        return False

    base_url = f"https://api.telegram.org/bot{token}"
    message_text = _format_message(payload)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            message_response = await client.post(
                f"{base_url}/sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": message_text,
                    "disable_web_page_preview": True,
                },
            )
            if not message_response.is_success or not message_response.json().get("ok"):
                logger.warning("Telegram sendMessage failed: %s", message_response.text)
                return False

            if not file_paths:
                return True

            media = []
            files = []
            handles = []
            try:
                for index, path in enumerate(file_paths):
                    attach_name = f"file{index}"
                    media.append({"type": "photo", "media": f"attach://{attach_name}"})
                    handle = path.open("rb")
                    handles.append(handle)
                    files.append((attach_name, (path.name, handle, "application/octet-stream")))
                media_response = await client.post(
                    f"{base_url}/sendMediaGroup",
                    data={
                        "chat_id": chat_id,
                        "media": json.dumps(media, ensure_ascii=False),
                    },
                    files=files,
                )
            finally:
                for handle in handles:
                    handle.close()

            if not media_response.is_success or not media_response.json().get("ok"):
                logger.warning("Telegram sendMediaGroup failed: %s", media_response.text)
                return False
    except Exception as exc:
        logger.exception("Telegram feedback send failed: %s", exc)
        return False

    return True
