from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from app.core.schema import DocumentSchema


def _build_conf_map(tokens: Optional[Iterable[Dict[str, Any]]]) -> Dict[str, float]:
    """Build a fast lookup from token id to its confidence.

    Accepts a list/iterable of OCR tokens where each token is expected to have
    keys: 'id' (str) and 'conf' (float). Returns a mapping id -> conf.
    """
    conf_map: Dict[str, float] = {}
    if not tokens:
        return conf_map
    for token in tokens:
        try:
            tid = str(token.get("id"))
            if not tid or tid == "None":
                continue
            conf_val = float(token.get("conf", 0.0))
            # Clamp to [0, 1]
            if conf_val < 0.0:
                conf_val = 0.0
            elif conf_val > 1.0:
                conf_val = 1.0
            conf_map[tid] = conf_val
        except Exception:
            # Best-effort: skip malformed tokens
            continue
    return conf_map


def score_field(
    field_key: str,
    field_data: Dict[str, Any],
    ocr_tokens: Any,
    schema: Optional[DocumentSchema],
) -> float:
    """Compute field confidence from OCR token confidences when available.

    Strategy:
    - If the field carries 'token_refs', compute the average confidence of the
      referenced OCR tokens (by id). If none of the refs resolve, fall back to 1.0.
    - If there are no token refs or tokens are unavailable, fall back to 1.0.

    This keeps existing behavior stable while starting to use OCR confidences
    wherever we have explicit token alignment.
    """

    try:
        token_refs = field_data.get("token_refs") or []
        if not isinstance(token_refs, list):
            token_refs = []

        conf_map = _build_conf_map(ocr_tokens)
        if token_refs and conf_map:
            confs: list[float] = []
            for ref in token_refs:
                # Support both string ids and numeric indices serialized as strings
                ref_id = str(ref)
                if ref_id in conf_map:
                    confs.append(conf_map[ref_id])
                else:
                    # Optionally support bare numeric index (best-effort)
                    try:
                        idx = int(ref_id)
                    except Exception:
                        idx = None
                    if idx is not None:
                        # Attempt positional lookup if ocr_tokens is indexable
                        try:
                            token = ocr_tokens[idx]
                            if token and str(token.get("id")) in conf_map:
                                confs.append(conf_map[str(token["id"])])
                            elif token and "conf" in token:
                                val = float(token.get("conf", 0.0))
                                if val < 0.0:
                                    val = 0.0
                                elif val > 1.0:
                                    val = 1.0
                                confs.append(val)
                        except Exception:
                            pass
            if confs:
                # Average of referenced token confidences
                avg = sum(confs) / len(confs)
                # Clamp for safety
                if avg < 0.0:
                    avg = 0.0
                elif avg > 1.0:
                    avg = 1.0
                return float(avg)

        # Fallback: no usable token refs → neutral high confidence to avoid regressions
        return 1.0
    except Exception:
        # Defensive: never break pipeline due to scoring
        return 1.0


def score_fields(
    fields: Dict[str, Dict[str, Any]],
    ocr_payload: Dict[str, Any],
    schema: DocumentSchema,
) -> Dict[str, Dict[str, Any]]:
    scored: Dict[str, Dict[str, Any]] = {}
    tokens = (ocr_payload or {}).get("tokens")
    for key, data in fields.items():
        enriched = dict(data)
        enriched["confidence"] = score_field(key, data, tokens, schema)
        scored[key] = enriched
    return scored

