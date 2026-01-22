from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

TELEGRAM_BOT_TOKEN_OVERRIDE = "8576804170:AAFPr5Tzjpe9mzSgBu8WgxkJQr_O_gPeqwM"
TELEGRAM_CHAT_ID_OVERRIDE = "-5216421758"
FEEDBACK_TYPE_LABELS = {
    "problem": "Проблема",
    "improvement": "Предложение по улучшению",
}


def _get_env(*names: str) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _feedback_root() -> Path:
    explicit_root = _get_env("SUPPLYHUB_FEEDBACK_ROOT", "FEEDBACK_ROOT")
    if explicit_root:
        return Path(explicit_root)
    base_dir = _get_env("SUPPLYHUB_BASE_DIR") or "/srv/supplyhub"
    return Path(base_dir) / "feedback"


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


def _send_message(token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(
        url,
        data={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=10,
    )
    if response.status_code != 200:
        return False
    payload = response.json()
    return bool(payload.get("ok"))


def _send_media_group(token: str, chat_id: str, files: List[Path]) -> bool:
    if not files:
        return True
    url = f"https://api.telegram.org/bot{token}/sendMediaGroup"
    media = []
    handles = []
    file_payload: List[Tuple[str, Tuple[str, Any, str]]] = []
    try:
        for index, path in enumerate(files):
            attach_name = f"file{index}"
            media.append({"type": "photo", "media": f"attach://{attach_name}"})
            handle = path.open("rb")
            handles.append(handle)
            file_payload.append((attach_name, (path.name, handle, "application/octet-stream")))
        response = requests.post(
            url,
            data={
                "chat_id": chat_id,
                "media": json.dumps(media, ensure_ascii=False),
            },
            files=file_payload,
            timeout=20,
        )
    finally:
        for handle in handles:
            handle.close()
    if response.status_code != 200:
        return False
    payload = response.json()
    return bool(payload.get("ok"))


def _send_payload(payload: Dict[str, Any], files_dir: Path) -> bool:
    token = TELEGRAM_BOT_TOKEN_OVERRIDE or _get_env("SUPPLYHUB_TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN")
    chat_id = TELEGRAM_CHAT_ID_OVERRIDE or _get_env("SUPPLYHUB_TELEGRAM_CHAT_ID", "TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
    files = []
    for info in payload.get("files", []):
        stored_name = info.get("stored_name")
        if not stored_name:
            continue
        candidate = files_dir / stored_name
        if candidate.exists():
            files.append(candidate)
    message = _format_message(payload)
    if not _send_message(token, chat_id, message):
        return False
    return _send_media_group(token, chat_id, files)


def _load_payload(ticket_dir: Path) -> Dict[str, Any]:
    payload_path = ticket_dir / "payload.json"
    return json.loads(payload_path.read_text(encoding="utf-8"))


def _drain_pending(feedback_root: Path) -> int:
    pending_root = feedback_root / "pending"
    if not pending_root.exists():
        return 0
    sent_count = 0
    for ticket_dir in sorted(pending_root.iterdir()):
        if not ticket_dir.is_dir():
            continue
        try:
            payload = _load_payload(ticket_dir)
            files_dir = ticket_dir / "files"
            if _send_payload(payload, files_dir):
                shutil.rmtree(ticket_dir, ignore_errors=True)
                sent_count += 1
        except Exception as exc:
            print(f"Failed to send {ticket_dir.name}: {exc}")
    return sent_count


def _watch_pending(feedback_root: Path, interval: float) -> None:
    if interval < 2:
        interval = 2
    while True:
        try:
            sent = _drain_pending(feedback_root)
            if sent:
                print(f"Sent {sent} feedback item(s).")
        except Exception as exc:
            print(f"Watch loop error: {exc}")
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram feedback helper")
    subparsers = parser.add_subparsers(dest="command")

    send_parser = subparsers.add_parser("send", help="Send a single feedback ticket")
    send_parser.add_argument("ticket_dir", help="Path to feedback ticket directory")

    drain_parser = subparsers.add_parser("drain", help="Send all pending feedback tickets")
    drain_parser.add_argument(
        "--root",
        dest="root",
        default=None,
        help="Feedback root directory (defaults to SUPPLYHUB_BASE_DIR/feedback)",
    )

    watch_parser = subparsers.add_parser("watch", help="Continuously send pending feedback tickets")
    watch_parser.add_argument(
        "--root",
        dest="root",
        default=None,
        help="Feedback root directory (defaults to SUPPLYHUB_BASE_DIR/feedback)",
    )
    watch_parser.add_argument(
        "--interval",
        dest="interval",
        type=float,
        default=10,
        help="Polling interval in seconds (min 2)",
    )

    args = parser.parse_args()
    if args.command == "send":
        ticket_dir = Path(args.ticket_dir)
        payload = _load_payload(ticket_dir)
        files_dir = ticket_dir / "files"
        ok = _send_payload(payload, files_dir)
        if ok:
            shutil.rmtree(ticket_dir, ignore_errors=True)
            print("Sent.")
        else:
            print("Failed.")
        return

    if args.command == "drain":
        root = Path(args.root) if args.root else _feedback_root()
        count = _drain_pending(root)
        print(f"Sent {count} feedback item(s).")
        return

    if args.command == "watch":
        root = Path(args.root) if args.root else _feedback_root()
        print(f"Watching {root} (interval {args.interval}s). Press Ctrl+C to stop.")
        try:
            _watch_pending(root, args.interval)
        except KeyboardInterrupt:
            print("Stopped.")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
