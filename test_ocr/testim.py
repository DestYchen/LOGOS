import argparse
import base64
import pathlib
import uuid

import httpx


def build_payload(doc_id: str, file_path: pathlib.Path) -> dict:
    payload = {
        "doc_id": doc_id,
        "file_path": str(file_path),
        "file_name": file_path.name,
        "file_suffix": file_path.suffix,
    }
    try:
        file_bytes = file_path.read_bytes()
    except Exception as exc:
        raise RuntimeError(f"Failed to read file {file_path}") from exc
    payload["file_bytes"] = base64.b64encode(file_bytes).decode("ascii")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OCR adapter test request")
    parser.add_argument(
        "file",
        type=pathlib.Path,
        help="Path to the document (pdf/image/text) to send to OCR",
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:9001/v1/ocr",
        help="OCR service URL",
    )
    args = parser.parse_args()

    doc_id = str(uuid.uuid4())
    payload = build_payload(doc_id, args.file)

    response = httpx.post(args.url, json=payload, timeout=120)
    response.raise_for_status()
    print(response.json())


if __name__ == "__main__":
    main()
