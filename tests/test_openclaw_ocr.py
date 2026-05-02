from __future__ import annotations

from app.mock_services import openclaw_ocr


def test_pdf_ocr_sends_original_pdf(monkeypatch) -> None:
    calls = []

    async def fake_call_openclaw(*, file_bytes: bytes, suffix: str, filename: str) -> str:
        calls.append({"file_bytes": file_bytes, "suffix": suffix, "filename": filename})
        return "hello world"

    monkeypatch.setattr(openclaw_ocr, "_call_openclaw", fake_call_openclaw)

    import asyncio

    tokens = asyncio.run(
        openclaw_ocr._tokens_from_file(file_bytes=b"%PDF test", suffix=".pdf", filename="sample.pdf")
    )

    assert calls == [{"file_bytes": b"%PDF test", "suffix": ".pdf", "filename": "sample.pdf"}]
    assert [token["text"] for token in tokens] == ["hello", "world"]


def test_text_to_tokens_uses_page_number() -> None:
    tokens = openclaw_ocr._text_to_tokens("first second", page=3)

    assert [token["id"] for token in tokens] == ["p3_t0", "p3_t1"]
    assert {token["page"] for token in tokens} == {3}


def test_image_resize_respects_max_pixels(monkeypatch) -> None:
    from io import BytesIO

    from PIL import Image

    image = Image.new("RGB", (100, 100), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    monkeypatch.setattr(openclaw_ocr, "OPENCLAW_OCR_MAX_PIXELS", 2500)
    resized_bytes, suffix = openclaw_ocr._maybe_resize_image(buffer.getvalue(), ".png")

    resized = Image.open(BytesIO(resized_bytes))
    assert suffix == ".png"
    assert resized.size[0] * resized.size[1] <= 2500
