import argparse
import base64
import pathlib
import uuid
from typing import Dict

import httpx


def build_payload(doc_id: str, file_path: pathlib.Path) -> Dict:
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
    parser.add_argument("file", type=pathlib.Path, help="Path to the document (pdf/image/text)")
    parser.add_argument("--url", default="http://127.0.0.1:9001/v1/ocr", help="OCR service URL")
    args = parser.parse_args()

    print(f"[ENTRY] url={args.url} file={args.file}", flush=True)
    if not args.file.exists():
        print("[ARG ERROR] file not found", flush=True)
        return

    doc_id = str(uuid.uuid4())
    print(f"[BUILD] doc_id={doc_id}", flush=True)
    try:
        payload = build_payload(doc_id, args.file)
    except Exception as e:
        print(f"[READ_ERR] {type(e).__name__}: {e}", flush=True)
        raise

    try:
        size = args.file.stat().st_size
    except Exception:
        size = -1
    print(f"[READY] suffix={args.file.suffix} size={size} bytes", flush=True)

    def log_request(req: httpx.Request) -> None:
        print(f"[REQ] {req.method} {req.url}", flush=True)

    def log_response(resp: httpx.Response) -> None:
        print(f"[RESP] {resp.status_code} {resp.reason_phrase}", flush=True)

    try:
        with httpx.Client(
            timeout=60.0,
            event_hooks={"request": [log_request], "response": [log_response]},
        ) as client:
            print("[POST] sending...", flush=True)
            resp = client.post(args.url, json=payload)

        print("[HEADERS]", dict(resp.headers), flush=True)
        ctype = resp.headers.get("content-type", "")
        if "application/json" in ctype.lower():
            try:
                data = resp.json()
                print("[BODY JSON]", data, flush=True)
                if isinstance(data, dict) and "detail" in data:
                    print("[DETAIL]", data["detail"], flush=True)
            except Exception as je:
                print("[BODY RAW]", resp.text[:1000], f"(json error: {je})", flush=True)
        else:
            print("[BODY RAW]", resp.text[:1000], flush=True)

        resp.raise_for_status()
        print("[OK DONE]", flush=True)
    except httpx.HTTPStatusError as e:
        r = e.response
        print(f"[HTTP ERR] {r.status_code} {r.reason_phrase}", flush=True)
        try:
            print("[ERR JSON]", r.json(), flush=True)
        except Exception:
            print("[ERR RAW]", r.text[:1000], flush=True)
        print(f"[CONTEXT] doc_id={doc_id} suffix={args.file.suffix} size={size}", flush=True)
        raise
    except httpx.RequestError as e:
        print(f"[NET ERR] {type(e).__name__}: {e}", flush=True)
        raise
    except Exception as e:
        print(f"[EXC] {type(e).__name__}: {e}", flush=True)
        raise


if __name__ == "__main__":
    main()
