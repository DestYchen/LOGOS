import argparse
import asyncio
import pathlib
import uuid
from pprint import pprint

from app.services.ocr import run_ocr


async def _run(path: pathlib.Path, langs: tuple[str, ...]) -> None:
    doc_id = uuid.uuid4()
    result = await run_ocr(doc_id, path, file_name=path.name, languages=langs)
    print(f"[DOC] {doc_id} tokens={len(result.get('tokens', []))}")
    pprint(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run in-process OCR using dots.ocr + vLLM")
    parser.add_argument("file", type=pathlib.Path, help="Path to the document (pdf/image/text)")
    parser.add_argument(
        "--langs",
        nargs="*",
        default=("zh", "en", "ru"),
        help="Preferred languages passed to the OCR service",
    )
    args = parser.parse_args()

    if not args.file.exists():
        raise SystemExit(f"File not found: {args.file}")

    asyncio.run(_run(args.file, tuple(args.langs)))


if __name__ == "__main__":
    main()
