import json
import pathlib
import uuid
from typing import Optional

import httpx

# --- Configuration ---------------------------------------------------------
DOC_TYPE = "INVOICE"
DOC_TEXT_PATH = pathlib.Path(r"test_ocr/ocr/invoice_text.txt")
TOKENS_PATH: Optional[pathlib.Path] = pathlib.Path(r"test_ocr/ocr/invoice_tokens.json")
FILE_NAME: Optional[str] = "INV 019246 04092019.pdf"
SERVICE_URL = "http://127.0.0.1:9002/v1/fill"
# ---------------------------------------------------------------------------


def load_tokens(path: pathlib.Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    data = json.loads(text)
    if isinstance(data, list):
        return data
    tokens = data.get("tokens")
    if isinstance(tokens, list):
        return tokens
    pages = data.get("pages")
    if isinstance(pages, list) and pages:
        return pages[0].get("tokens", [])
    return []


def main() -> None:
    if not DOC_TEXT_PATH.exists():
        raise FileNotFoundError(f"Text file not found: {DOC_TEXT_PATH}")

    doc_id = str(uuid.uuid4())
    doc_text = DOC_TEXT_PATH.read_text(encoding="utf-8")

    payload = {
        "doc_id": doc_id,
        "doc_type": DOC_TYPE,
        "doc_text": doc_text,
    }
    if FILE_NAME:
        payload["file_name"] = FILE_NAME
    if TOKENS_PATH:
        if not TOKENS_PATH.exists():
            raise FileNotFoundError(f"Tokens file not found: {TOKENS_PATH}")
        payload["tokens"] = load_tokens(TOKENS_PATH)

    response = httpx.post(SERVICE_URL, json=payload, timeout=120)
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
