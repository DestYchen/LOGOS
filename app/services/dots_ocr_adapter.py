from __future__ import annotations

import asyncio
import gc
import importlib.util
import logging
import math
import os
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Iterable, List, Optional, Tuple
from types import ModuleType

logger = logging.getLogger(__name__)

# Text-only prompt: avoids any picture/image datatype; outputs a flat JSON array
# with elements containing only bbox, category, and text.
PROMPT_WITHOUT_PICTURE = (
    """Please output the layout information from the PDF image, including each layout element's bbox, its category, and the corresponding text content within the bbox. 1. Bbox format: [x1, y1, x2, y2] 2. Layout Categories: The possible categories are ['Caption', 'Footnote', 'Formula', 'List-item', 'Page-footer', 'Page-header', 'Section-header', 'Table', 'Text', 'Title']. 3. Text Extraction & Formatting Rules: - Formula: Format its text as LaTeX. - Table: Format its text as HTML. - All Others (Text, Title, etc.): Format their text as Markdown. - When an element contains textual content that resembles paragraphs, titles, captions, or tables, prefer the closest text-oriented category instead of using picture-like labels. 4. Constraints: - The output text must be the original text from the image, with no translation. - All layout elements must be sorted according to human reading order. 5. Final Output: Output a single JSON array (no prose), where each element is an object with keys: bbox (as [x1, y1, x2, y2]), category (one of the listed categories), and text (string). Do not include any keys other than bbox, category, and text. Do not include any explanations or extra text outside the JSON array."""
)


def _find_dots_repo() -> Path:
    env_path = os.getenv("DOTS_OCR_REPO", "").strip()
    candidates: Iterable[Optional[Path]] = [
        Path(env_path) if env_path else None,
        Path(__file__).resolve().parents[2] / "vendor" / "dots.ocr",
        Path(__file__).resolve().parents[2] / ".." / "dots" / "dots.ocr",
        Path(__file__).resolve().parents[2] / "dots.ocr",
    ]
    for candidate in candidates:
        if candidate and (candidate / "dots_ocr").exists():
            return candidate
    raise RuntimeError("dots.ocr repository not found. Set DOTS_OCR_REPO or place dots.ocr next to LOGOS.")


def _load_module_from_path(name: str, file_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, str(file_path))
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"Cannot load module {name} from {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


_DOTS_REPO = _find_dots_repo()
_UTILS_DIR = _DOTS_REPO / "dots_ocr" / "utils"

# Create lightweight package stubs to satisfy intra-utils imports
_dots_pkg = ModuleType("dots_ocr")
_dots_pkg.__path__ = [str((_DOTS_REPO / "dots_ocr").resolve())]  # type: ignore[attr-defined]
sys.modules.setdefault("dots_ocr", _dots_pkg)

_utils_pkg = ModuleType("dots_ocr.utils")
_utils_pkg.__path__ = [str(_UTILS_DIR.resolve())]  # type: ignore[attr-defined]
sys.modules.setdefault("dots_ocr.utils", _utils_pkg)

# Load utils modules under their canonical names so their imports work
_consts = _load_module_from_path("dots_ocr.utils.consts", _UTILS_DIR / "consts.py")
_doc_utils = _load_module_from_path("dots_ocr.utils.doc_utils", _UTILS_DIR / "doc_utils.py")
_image_utils = _load_module_from_path("dots_ocr.utils.image_utils", _UTILS_DIR / "image_utils.py")
_layout_utils = _load_module_from_path("dots_ocr.utils.layout_utils", _UTILS_DIR / "layout_utils.py")
_prompts = _load_module_from_path("dots_ocr.utils.prompts", _UTILS_DIR / "prompts.py")

# Re-export required symbols locally without importing dots_ocr package (avoids torch)
MAX_PIXELS = getattr(_consts, "MAX_PIXELS")
MIN_PIXELS = getattr(_consts, "MIN_PIXELS")
image_extensions = getattr(_consts, "image_extensions")
load_images_from_pdf = getattr(_doc_utils, "load_images_from_pdf")
fetch_image = getattr(_image_utils, "fetch_image")
get_image_by_fitz_doc = getattr(_image_utils, "get_image_by_fitz_doc")
PILimage_to_base64 = getattr(_image_utils, "PILimage_to_base64")
post_process_output = getattr(_layout_utils, "post_process_output")
dict_promptmode_to_prompt = getattr(_prompts, "dict_promptmode_to_prompt")

# Generation budget and preprocessing defaults (match dots.ocr service)
DEFAULT_MAX_COMPLETION_TOKENS = int(os.getenv("DOTS_OCR_SERVICE_MAX_COMPLETION_TOKENS", "24000"))
MAX_COMPLETION_TOKENS_CAP = int(os.getenv("DOTS_OCR_SERVICE_MAX_COMPLETION_TOKENS_CAP", "4096"))
DEFAULT_DPI = int(os.getenv("DOTS_OCR_SERVICE_DPI", "200"))
DEFAULT_MAX_PIXELS = int(os.getenv("DOTS_OCR_SERVICE_MAX_PIXELS", "1000000"))
_default_min_pixels = os.getenv("DOTS_OCR_SERVICE_MIN_PIXELS")
DEFAULT_MIN_PIXELS = int(_default_min_pixels) if _default_min_pixels else None
DEFAULT_FITZ_PREPROCESS = os.getenv("DOTS_OCR_SERVICE_FITZ_PREPROCESS", "true").lower() in {"1", "true", "yes", "on"}

# Text refinement defaults (for filling missing OCR text via vLLM follow-up prompts)
DEFAULT_TEXT_REFINE_ENABLED = os.getenv("DOTS_OCR_VLLM_TEXT_REFINE", "1").lower() in {"1", "true", "yes", "on"}
try:
    DEFAULT_TEXT_REFINE_LIMIT = int(os.getenv("DOTS_OCR_VLLM_TEXT_REFINE_LIMIT", "32"))
except Exception:
    DEFAULT_TEXT_REFINE_LIMIT = 32
try:
    DEFAULT_TEXT_REFINE_MARGIN = int(os.getenv("DOTS_OCR_VLLM_TEXT_REFINE_MARGIN", "4"))
except Exception:
    DEFAULT_TEXT_REFINE_MARGIN = 4
try:
    DEFAULT_TEXT_REFINE_MAX_TOKENS = int(os.getenv("DOTS_OCR_VLLM_TEXT_MAX_TOKENS", "768"))
except Exception:
    DEFAULT_TEXT_REFINE_MAX_TOKENS = 768


class DotsOCRError(RuntimeError):
    """Raised when dots.ocr inference fails."""


@dataclass
class RuntimeConfig:
    dpi: int = DEFAULT_DPI
    min_pixels: Optional[int] = DEFAULT_MIN_PIXELS
    max_pixels: Optional[int] = DEFAULT_MAX_PIXELS
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS
    fitz_preprocess: bool = DEFAULT_FITZ_PREPROCESS


class DotsOCRAdapter:
    """In-process adapter replicating the former dots.ocr service behaviour."""

    def __init__(self) -> None:
        self._parser = None  # No HF parser; keep for backward compatibility
        # Removed torch device management; vLLM is the only backend
        self._lock = asyncio.Lock()
        self._startup_lock = asyncio.Lock()
        self._use_vllm = True
        self._vllm_base: Optional[str] = None
        self._vllm_model: str = "model"
        self._vllm_temp: float = 0.1
        self._vllm_top_p: float = 0.9
        self._vllm_client = None

    async def run(
        self,
        doc_id: uuid.UUID,
        file_path: Path,
        *,
        options: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        await self._ensure_started()
        runtime_cfg = self._merge_config(options)

        if not file_path.exists():
            raise DotsOCRError(f"file_not_found: {file_path}")

        start = perf_counter()
        try:
            async with self._lock:
                tokens = await asyncio.to_thread(self._process_document, file_path, runtime_cfg, doc_id)
            return tokens
        finally:
            self._cleanup_memory()
            logger.info("dots.ocr inference doc_id=%s elapsed=%.2fs", doc_id, perf_counter() - start)

    async def _ensure_started(self) -> None:
        # Nothing heavy to initialize beyond vLLM client configuration
        async with self._startup_lock:
            await asyncio.to_thread(self._startup_sync)

    def _startup_sync(self) -> None:
        # vLLM-only backend has no heavy in-process model to load

        # Force vLLM backend; ignore HF/torch
        self._use_vllm = True

        vllm_base = os.getenv("DOTS_OCR_VLLM_BASE", "").strip()
        vllm_host = os.getenv("DOTS_OCR_VLLM_HOST", "localhost").strip()
        vllm_port = os.getenv("DOTS_OCR_VLLM_PORT", "8010").strip()
        self._vllm_model = os.getenv("DOTS_OCR_VLLM_MODEL", "model").strip() or "model"
        try:
            self._vllm_temp = float(os.getenv("DOTS_OCR_VLLM_TEMPERATURE", str(self._vllm_temp)))
        except Exception:
            pass
        try:
            self._vllm_top_p = float(os.getenv("DOTS_OCR_VLLM_TOP_P", str(self._vllm_top_p)))
        except Exception:
            pass

        if vllm_base:
            self._vllm_base = vllm_base.rstrip("/")
        else:
            self._vllm_base = f"http://{vllm_host}:{vllm_port}/v1"

        use_hf = not self._use_vllm
        logger.info("Initialising dots.ocr (vLLM client only)")

        if use_hf:
            # HF/torch backend removed
            raise RuntimeError("HF/torch backend is disabled; only vLLM is supported.")
        else:
            logger.info("dots.ocr vLLM client initialised (base=%s, model=%s)", self._vllm_base, self._vllm_model)
            try:
                from openai import OpenAI

                self._vllm_client = OpenAI(api_key="EMPTY", base_url=self._vllm_base)
            except Exception as exc:  # pragma: no cover - optional dependency
                logger.warning("Failed to initialize vLLM client: %s", exc)
                self._vllm_client = None

    def _merge_config(self, options: Optional[Dict[str, Any]]) -> RuntimeConfig:
        cfg = RuntimeConfig()
        if not options:
            return cfg

        if "dpi" in options:
            try:
                cfg.dpi = int(options["dpi"])
            except (TypeError, ValueError):
                logger.warning("Invalid dpi option: %s", options["dpi"])

        if "min_pixels" in options:
            try:
                cfg.min_pixels = int(options["min_pixels"])
            except (TypeError, ValueError):
                logger.warning("Invalid min_pixels option: %s", options["min_pixels"])

        if "max_pixels" in options:
            try:
                cfg.max_pixels = int(options["max_pixels"])
            except (TypeError, ValueError):
                logger.warning("Invalid max_pixels option: %s", options["max_pixels"])

        if "max_completion_tokens" in options:
            try:
                cfg.max_completion_tokens = int(options["max_completion_tokens"])
            except (TypeError, ValueError):
                logger.warning("Invalid max_completion_tokens option: %s", options["max_completion_tokens"])

        if "fitz_preprocess" in options:
            cfg.fitz_preprocess = bool(options["fitz_preprocess"])

        if cfg.max_pixels is not None:
            cfg.max_pixels = max(MIN_PIXELS, min(cfg.max_pixels, MAX_PIXELS))
        if cfg.min_pixels is not None:
            cfg.min_pixels = max(MIN_PIXELS, min(cfg.min_pixels, MAX_PIXELS))
        if cfg.min_pixels and cfg.max_pixels and cfg.min_pixels > cfg.max_pixels:
            cfg.min_pixels = cfg.max_pixels

        return cfg

    def _process_document(self, file_path: Path, runtime_cfg: RuntimeConfig, doc_id: uuid.UUID) -> List[Dict[str, Any]]:

        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            images = load_images_from_pdf(str(file_path), dpi=runtime_cfg.dpi)
            if not images:
                raise DotsOCRError("pdf_without_pages")
            tokens: List[Dict[str, Any]] = []
            for page_idx, image in enumerate(images):
                # Best-effort: save page preview before parsing
                try:
                    self._save_preview_image(file_path, doc_id, page_idx + 1, image)
                except Exception:
                    logger.debug("Failed to save preview image (pdf page)", exc_info=True)
                cells, page_size, token_confidences = self._parse_page(
                    image,
                    page_idx,
                    runtime_cfg,
                    doc_id=doc_id,
                    source="pdf",
                )
                tokens.extend(self._cells_to_tokens(cells, page_idx, page_size, token_confidences))
            return tokens

        if suffix in image_extensions:
            origin_image = fetch_image(str(file_path))
            # Best-effort: save single-page preview before parsing
            try:
                self._save_preview_image(file_path, doc_id, 1, origin_image)
            except Exception:
                logger.debug("Failed to save preview image (single image)", exc_info=True)
            cells, page_size, token_confidences = self._parse_page(
                origin_image,
                0,
                runtime_cfg,
                doc_id=doc_id,
                source="image",
            )
            return self._cells_to_tokens(cells, 0, page_size, token_confidences)

        raise DotsOCRError(f"unsupported_file_type:{suffix}")

    def _parse_page(
        self,
        origin_image,
        page_idx: int,
        runtime_cfg: RuntimeConfig,
        *,
        doc_id: uuid.UUID,
        source: str,
    ) -> Tuple[List[Dict[str, Any]], Tuple[int, int], List[float]]:
        min_pixels = runtime_cfg.min_pixels if runtime_cfg.min_pixels is not None else DEFAULT_MIN_PIXELS
        max_pixels = runtime_cfg.max_pixels if runtime_cfg.max_pixels is not None else DEFAULT_MAX_PIXELS

        if max_pixels is not None:
            max_pixels = min(max_pixels, MAX_PIXELS)
        if min_pixels is not None:
            min_pixels = max(min_pixels, MIN_PIXELS)

        if source == "image" and runtime_cfg.fitz_preprocess:
            working_image = get_image_by_fitz_doc(origin_image, target_dpi=runtime_cfg.dpi)
            working_image = fetch_image(working_image, min_pixels=min_pixels, max_pixels=max_pixels)
        else:
            working_image = fetch_image(origin_image, min_pixels=min_pixels, max_pixels=max_pixels)

        # Build the prompt text directly (was parser.get_prompt). Default to the
        # provided text-only prompt unless an explicit override is set.
        prompt = os.getenv("DOTS_OCR_PROMPT_OVERRIDE")
        if not prompt:
            prompt = PROMPT_WITHOUT_PICTURE

        # Optionally log the exact prompt to console for verification
        try:
            if str(os.getenv("DOTS_OCR_DEBUG_LOG_PROMPT", "1")).lower() in {"1", "true", "yes", "on"}:
                logger.warning("OCR PROMPT IN USE (len=%s): %s", len(prompt), prompt)
            else:
                logger.debug("OCR prompt length=%s (enable DOTS_OCR_DEBUG_LOG_PROMPT=1 to print)", len(prompt))
        except Exception:
            logger.debug("Failed to log OCR prompt", exc_info=True)

        # Only vLLM inference is supported
        response, token_confidences = self._inference_with_confidences_vllm(working_image, prompt)

        # Optional raw dump and console log of model output for debugging JSON truncation issues
        try:
            raw_text = response if isinstance(response, str) else str(response)

            if str(os.getenv("DOTS_OCR_DEBUG_DUMP_RAW", "")).lower() in {"1", "true", "yes", "on"}:
                dump_dir = Path(os.getenv("DOTS_OCR_DEBUG_DIR", ".debug_dotsocr")).resolve()
                dump_dir.mkdir(parents=True, exist_ok=True)
                dump_path = dump_dir / f"{doc_id}_p{page_idx}_raw.txt"
                with open(dump_path, "w", encoding="utf-8") as f:
                    f.write(raw_text)
                logger.warning(
                    "Saved raw vLLM response chars=%s doc_id=%s page=%s to %s",
                    len(raw_text),
                    doc_id,
                    page_idx,
                    dump_path,
                )
            else:
                logger.debug(
                    "Raw vLLM response length=%s doc_id=%s page=%s (set DOTS_OCR_DEBUG_DUMP_RAW=1 to save)",
                    len(raw_text),
                    doc_id,
                    page_idx,
                )

            if str(os.getenv("DOTS_OCR_DEBUG_LOG_RAW", "")).lower() in {"1", "true", "yes", "on"}:
                try:
                    chunk_sz = int(os.getenv("DOTS_OCR_DEBUG_LOG_CHUNK", "8000"))
                except Exception:
                    chunk_sz = 8000
                chunk_sz = max(512, min(32768, chunk_sz))
                total = len(raw_text)
                logger.warning("RAW OCR BEGIN doc_id=%s page=%s total_chars=%s", doc_id, page_idx, total)
                for i in range(0, total, chunk_sz):
                    part = raw_text[i : i + chunk_sz]
                    logger.warning(
                        "RAW OCR CHUNK doc_id=%s page=%s range=%s-%s:\n%s",
                        doc_id,
                        page_idx,
                        i,
                        min(i + chunk_sz, total),
                        part,
                    )
                logger.warning("RAW OCR END doc_id=%s page=%s", doc_id, page_idx)
        except Exception:
            logger.debug("Failed to dump raw vLLM response", exc_info=True)

        def _decode(model_response: Any) -> Tuple[List[Dict[str, Any]], bool, Dict[str, Any]]:
            return post_process_output(
                model_response,
                "prompt_layout_all_en",
                origin_image,
                working_image,
                min_pixels=min_pixels,
                max_pixels=max_pixels,
            )

        cells, filtered, meta = _decode(response)

        initial_budget = runtime_cfg.max_completion_tokens or DEFAULT_MAX_COMPLETION_TOKENS
        retry_triggered = (
            filtered
            or not meta.get("raw_closed", True)
            or meta.get("json_recovered", False)
            or meta.get("fallback_used", False)
        )

        if retry_triggered:
            retry_budget = min(MAX_COMPLETION_TOKENS_CAP, max(initial_budget * 2, initial_budget + 512))
            if retry_budget > initial_budget:
                logger.debug(
                    "Retrying OCR generation for page %s with max_new_tokens=%s (initial=%s)",
                    page_idx,
                    retry_budget,
                    initial_budget,
                )
                response, token_confidences = self._inference_with_confidences_vllm(
                    working_image,
                    prompt,
                    max_new_tokens=retry_budget,
                )
                cells, filtered, meta = _decode(response)

        if filtered:
            raise DotsOCRError(f"ocr_decoding_failed: page={page_idx}")

        if not isinstance(cells, list):
            raise DotsOCRError(f"ocr_cells_invalid: page={page_idx} type={type(cells)}")

        cells = self._maybe_refine_cells_with_text(
            origin_image,
            cells,
            runtime_cfg,
            doc_id=doc_id,
            page_idx=page_idx,
        )

        return cells, origin_image.size, token_confidences

    # HF/torch inference path removed

    def _maybe_refine_cells_with_text(
        self,
        origin_image,
        cells: List[Dict[str, Any]],
        runtime_cfg: RuntimeConfig,
        *,
        doc_id: uuid.UUID,
        page_idx: int,
    ) -> List[Dict[str, Any]]:
        if not DEFAULT_TEXT_REFINE_ENABLED:
            return cells

        if not cells:
            return cells

        pil_image = origin_image if hasattr(origin_image, "crop") and hasattr(origin_image, "size") else None
        if pil_image is None:
            try:
                pil_image = fetch_image(origin_image)
            except Exception:
                logger.debug("Unable to coerce origin image for text refinement", exc_info=True)
                return cells

        if pil_image is None:
            return cells

        prompt = os.getenv("DOTS_OCR_PROMPT_TEXT_OVERRIDE")
        if not prompt:
            prompt = dict_promptmode_to_prompt.get("prompt_ocr", "Extract the text content from this image.")

        try:
            max_refine = int(os.getenv("DOTS_OCR_VLLM_TEXT_REFINE_LIMIT", str(DEFAULT_TEXT_REFINE_LIMIT)))
        except Exception:
            max_refine = DEFAULT_TEXT_REFINE_LIMIT
        if max_refine <= 0:
            return cells

        try:
            margin = int(os.getenv("DOTS_OCR_VLLM_TEXT_REFINE_MARGIN", str(DEFAULT_TEXT_REFINE_MARGIN)))
        except Exception:
            margin = DEFAULT_TEXT_REFINE_MARGIN
        try:
            max_tokens = int(os.getenv("DOTS_OCR_VLLM_TEXT_MAX_TOKENS", str(DEFAULT_TEXT_REFINE_MAX_TOKENS)))
        except Exception:
            max_tokens = DEFAULT_TEXT_REFINE_MAX_TOKENS

        min_pixels = runtime_cfg.min_pixels if runtime_cfg.min_pixels is not None else DEFAULT_MIN_PIXELS or MIN_PIXELS
        max_pixels = runtime_cfg.max_pixels if runtime_cfg.max_pixels is not None else DEFAULT_MAX_PIXELS or MAX_PIXELS

        refined = 0
        filled = 0
        for cell in cells:
            if refined >= max_refine:
                break
            bbox = cell.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            text = str(cell.get("text") or "").strip()
            if text:
                continue
            category = str(cell.get("category") or "").lower()
            if category == "picture":
                continue

            extracted = self._extract_text_for_bbox_vllm(
                pil_image,
                bbox,
                prompt,
                min_pixels=min_pixels,
                max_pixels=max_pixels,
                margin=margin,
                max_tokens=max_tokens,
                doc_id=doc_id,
                page_idx=page_idx,
            )
            refined += 1
            if not extracted:
                continue
            cell["text"] = extracted
            filled += 1

        if filled:
            logger.debug(
                "Filled missing OCR text entries doc_id=%s page=%s filled=%s attempts=%s",
                doc_id,
                page_idx,
                filled,
                refined,
            )

        return cells

    def _extract_text_for_bbox_vllm(
        self,
        origin_image,
        bbox: Iterable[Any],
        prompt: str,
        *,
        min_pixels: Optional[int],
        max_pixels: Optional[int],
        margin: int,
        max_tokens: int,
        doc_id: uuid.UUID,
        page_idx: int,
    ) -> str:
        try:
            x1, y1, x2, y2 = [int(round(float(v))) for v in bbox]
        except Exception:
            return ""

        width, height = origin_image.size if hasattr(origin_image, "size") else (None, None)
        if not width or not height:
            return ""

        x1 = max(0, min(width - 1, x1))
        x2 = max(0, min(width, x2))
        y1 = max(0, min(height - 1, y1))
        y2 = max(0, min(height, y2))
        if x2 <= x1 or y2 <= y1:
            return ""

        margin = max(0, margin)
        x1 = max(0, x1 - margin)
        y1 = max(0, y1 - margin)
        x2 = min(width, x2 + margin)
        y2 = min(height, y2 + margin)

        try:
            region = origin_image.crop((x1, y1, x2, y2))
        except Exception:
            logger.debug("Failed to crop region for text refinement", exc_info=True)
            return ""

        try:
            region = fetch_image(region, min_pixels=min_pixels, max_pixels=max_pixels)
        except Exception:
            logger.debug("Failed to preprocess region for text refinement", exc_info=True)
            return ""

        try:
            response, _ = self._inference_with_confidences_vllm(
                region,
                prompt,
                max_new_tokens=max(32, min(max_tokens, DEFAULT_MAX_COMPLETION_TOKENS)),
            )
        except Exception:
            logger.debug("Text refinement inference failed doc_id=%s page=%s", doc_id, page_idx, exc_info=True)
            return ""

        if not response:
            return ""

        text = str(response).strip()
        if text.startswith("\"") and text.endswith("\"") and len(text) > 1:
            text = text[1:-1].strip()
        if text.startswith("`") and text.endswith("`") and len(text) > 1:
            text = text[1:-1].strip()

        return text

    def _inference_with_confidences_vllm(
        self,
        image,
        prompt: str,
        max_new_tokens: Optional[int] = None,
    ) -> Tuple[str, List[float]]:
        assert self._vllm_base is not None

        if self._vllm_client is None:
            try:
                from openai import OpenAI
            except Exception as exc:
                raise DotsOCRError("openai package is required for vLLM backend") from exc
            self._vllm_client = OpenAI(api_key="EMPTY", base_url=self._vllm_base)

        b64 = PILimage_to_base64(image)
        content = [
            {"type": "image_url", "image_url": {"url": b64}},
            {"type": "text", "text": f"<|img|><|imgpad|><|endofimg|>{prompt}"},
        ]

        try:
            if str(os.getenv("DOTS_OCR_DEBUG_LOG_PAYLOAD", "1")).lower() in {"1", "true", "yes", "on"}:
                logger.warning(
                    "vLLM request model=%s max_tokens=%s parts=%s [types=%s]",
                    self._vllm_model,
                    max_new_tokens or DEFAULT_MAX_COMPLETION_TOKENS,
                    len(content),
                    ",".join([p.get("type", "?") for p in content]),
                )
        except Exception:
            logger.debug("Failed to log vLLM payload meta", exc_info=True)

        params = {
            "model": self._vllm_model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.0,
            "top_p": 1.0,
            "logprobs": True,
            "top_logprobs": 1,
            "max_tokens": max_new_tokens or DEFAULT_MAX_COMPLETION_TOKENS,
        }

        resp = self._vllm_client.chat.completions.create(**params)
        text = resp.choices[0].message.content or ""
        token_confidences: List[float] = []

        try:
            logprobs_data = resp.choices[0].logprobs
            if logprobs_data and logprobs_data.content:
                for token_data in logprobs_data.content:
                    logprob = token_data.logprob
                    if logprob is not None:
                        prob = math.exp(float(logprob))
                        token_confidences.append(max(0.0, min(1.0, prob)))
        except (AttributeError, TypeError):
            token_confidences = []

        logger.debug(
            "vLLM generated %s tokens, conf: mean=%.3f, min=%.3f",
            len(token_confidences),
            sum(token_confidences) / len(token_confidences) if token_confidences else 0,
            min(token_confidences) if token_confidences else 0,
        )

        return text, token_confidences

    def _cells_to_tokens(
        self,
        cells: List[Dict[str, Any]],
        page_idx: int,
        page_size: Tuple[int, int],
        token_confidences: List[float],
    ) -> List[Dict[str, Any]]:
        tokens: List[Dict[str, Any]] = []
        page_width, page_height = page_size

        def _normalize_bbox(bbox: Iterable[float]) -> List[int]:
            quad = list(bbox)
            if len(quad) != 4:
                raise ValueError(f"Invalid bbox length {len(quad)}")
            x1, y1, x2, y2 = quad
            return [
                max(0, int(round(x1))),
                max(0, int(round(y1))),
                min(page_width, int(round(x2))),
                min(page_height, int(round(y2))),
            ]

        conf_iter = iter(token_confidences)

        for idx, cell in enumerate(cells):
            text = cell.get("text", "")
            if not text:
                continue
            try:
                bbox = _normalize_bbox(cell.get("bbox", [0, 0, 0, 0]))
            except Exception:
                bbox = [0, 0, 0, 0]

            try:
                conf = float(next(conf_iter))
            except StopIteration:
                conf = 0.0
            except Exception:
                conf = 0.0

            token = {
                "id": f"p{page_idx}_t{idx}",
                "text": text,
                "conf": max(0.0, min(1.0, conf)),
                "bbox": bbox,
                "page": page_idx + 1,
            }
            category = cell.get("category")
            if category:
                token["category"] = category
            tokens.append(token)

        return tokens

    @staticmethod
    def _cleanup_memory() -> None:
        gc.collect()
        # Torch is not used; skip GPU cache management

    def _save_preview_image(self, file_path: Path, doc_id: uuid.UUID, page_number: int, image_obj) -> None:
        """Save a preview PNG under batches/<batch>/preview/<doc_id>/page_<n>.png.

        Computes the batch base from the raw file path, resizes to configured max size,
        and writes a PNG file. Best-effort; failures are logged and ignored.
        """
        try:
            from PIL import Image  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.debug("PIL not available for preview saving: %s", exc)
            return

        # Compute base dir: <base>/raw/<filename> => <base>
        # Windows paths supported via pathlib
        raw_dir = file_path.parent
        base_dir = raw_dir.parent
        preview_dir = base_dir / "preview" / str(doc_id)
        preview_dir.mkdir(parents=True, exist_ok=True)

        # Coerce to PIL.Image
        if hasattr(image_obj, "copy") and hasattr(image_obj, "save"):
            pil_img = image_obj
        else:
            try:
                pil_img = fetch_image(image_obj)
            except Exception:
                logger.debug("Unable to coerce preview image", exc_info=True)
                return

        # Resize respecting aspect ratio
        max_w = 1280
        max_h = 960
        try:
            if get_settings:
                settings = get_settings()
                max_w = int(getattr(settings, "preview_max_width", max_w))
                max_h = int(getattr(settings, "preview_max_height", max_h))
        except Exception:
            pass

        try:
            img = pil_img.copy()
            img.thumbnail((max_w, max_h))
            out_path = preview_dir / f"page_{page_number}.png"
            img.save(out_path, format="PNG")
        except Exception:
            logger.debug("Failed to write preview image", exc_info=True)


_ADAPTER_INSTANCE: Optional[DotsOCRAdapter] = None
_ADAPTER_INIT_LOCK = asyncio.Lock()


async def get_dots_ocr_adapter() -> DotsOCRAdapter:
    global _ADAPTER_INSTANCE
    if _ADAPTER_INSTANCE is not None:
        return _ADAPTER_INSTANCE
    async with _ADAPTER_INIT_LOCK:
        if _ADAPTER_INSTANCE is None:
            _ADAPTER_INSTANCE = DotsOCRAdapter()
    return _ADAPTER_INSTANCE
try:
    from app.core.config import get_settings  # lightweight config
except Exception:  # pragma: no cover - adapter can run without settings during import
    get_settings = None  # type: ignore[assignment]
