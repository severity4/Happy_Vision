"""modules/gemini_batch.py — Gemini Batch API client for async photo analysis.

Batch mode trades immediacy (24h SLO) for 50% cost off realtime. Tier-1 paid
accounts only — free tier will get PERMISSION_DENIED on create.

Flow:
    1. build_jsonl_for_chunk(photos, ...) writes a JSONL file with inline
       base64 images — one line per photo, key = stable "p{index}".
    2. submit_batch(jsonl_path, ...) uploads via Files API and creates a
       batch job. Returns BatchSubmitResult(job_id, input_file_id).
    3. get_job_state(job_id) polls current status.
    4. fetch_results(job_id) downloads the output JSONL and yields per-photo
       (key, result_or_error, usage) triples.
    5. cancel_job(job_id) to abort.

Chunking: photos are capped by MAX_PHOTOS_PER_BATCH (3000) and the estimated
payload size cap MAX_PAYLOAD_BYTES (1.5 GB — Gemini's limit is 2 GB for the
uploaded JSONL, we leave headroom). Callers handle multi-chunk splitting.
"""

from __future__ import annotations

import base64
import io
import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from google import genai
from google.genai import types

from modules.gemini_vision import (
    ANALYSIS_SCHEMA,
    MODEL_MAP,
    SAFETY_SETTINGS,
    build_prompt,
    parse_response,
    resize_for_api,
)
from modules.logger import setup_logger

log = setup_logger("gemini_batch")

MAX_PHOTOS_PER_BATCH = 3000
MAX_PAYLOAD_BYTES = 1_500_000_000  # 1.5 GB (Gemini limit is 2 GB)

# Ended states — no more polling needed.
ENDED_STATES = {
    "JOB_STATE_SUCCEEDED",
    "JOB_STATE_FAILED",
    "JOB_STATE_CANCELLED",
    "JOB_STATE_EXPIRED",
    "JOB_STATE_PARTIALLY_SUCCEEDED",
}

# Billing page users are sent to when batch fails with a tier error.
BILLING_URL = "https://aistudio.google.com/app/plan_information"


class TierRequiredError(Exception):
    """Raised when Gemini rejects the batch create because the account is on
    the free tier. Surface a friendly CTA pointing at the billing page."""

    def __init__(self, message: str = ""):
        super().__init__(
            message
            or "批次模式需要 Google AI Studio 付費 Tier 1。請到 "
            "https://aistudio.google.com/app/plan_information 綁定信用卡後再試。"
        )


@dataclass
class BatchSubmitResult:
    job_id: str
    input_file_id: str
    photo_count: int
    payload_bytes: int


@dataclass
class BatchItemResult:
    """One photo's result parsed out of the batch output JSONL."""

    key: str
    result: dict | None  # parsed Gemini JSON, or None on error
    usage: dict | None  # {input_tokens, output_tokens, total_tokens, model}
    error: str | None  # human error message, set iff result is None


def _encode_photo(photo_path: str, max_size: int) -> bytes:
    """Read + resize + base64-encode a photo. Returns the b64 ASCII bytes."""
    raw = Path(photo_path).read_bytes()
    resized = resize_for_api(raw, max_size=max_size)
    return base64.b64encode(resized)


def _build_request_dict(photo_b64: bytes, model_name: str) -> dict:
    """Build the GenerateContentRequest dict for one photo. Matches the
    realtime call's schema/config exactly so output parses identically."""
    return {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": photo_b64.decode("ascii"),
                        }
                    },
                    {"text": build_prompt()},
                ]
            }
        ],
        "generation_config": {
            "temperature": 0,
            "response_mime_type": "application/json",
            "response_schema": ANALYSIS_SCHEMA,
        },
        "safety_settings": [
            {"category": s["category"], "threshold": s["threshold"]}
            for s in SAFETY_SETTINGS
        ],
    }


def build_jsonl_for_chunk(
    photos: list[str],
    model: str = "lite",
    max_size: int = 3072,
    out_path: Path | None = None,
) -> tuple[Path, list[tuple[str, str]], int]:
    """Serialise `photos` into a JSONL file suitable for client.files.upload.

    Returns (jsonl_path, [(key, photo_path), ...], payload_bytes).
    The key list lets the caller map output lines back to local paths; keys are
    zero-padded stable strings ("p00001") so lexical == insertion order.

    Raises ValueError if the photo list is empty or exceeds MAX_PHOTOS_PER_BATCH,
    and if the accumulated JSONL exceeds MAX_PAYLOAD_BYTES partway through
    (callers should chunk beforehand but we double-check)."""
    if not photos:
        raise ValueError("photos must not be empty")
    if len(photos) > MAX_PHOTOS_PER_BATCH:
        raise ValueError(
            f"photos={len(photos)} exceeds MAX_PHOTOS_PER_BATCH={MAX_PHOTOS_PER_BATCH}"
        )
    model_name = MODEL_MAP.get(model, MODEL_MAP["lite"])

    if out_path is None:
        out_path = Path(tempfile.mkstemp(prefix="happyvision_batch_", suffix=".jsonl")[1])
    key_map: list[tuple[str, str]] = []
    total_bytes = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for idx, photo in enumerate(photos):
            try:
                b64 = _encode_photo(photo, max_size=max_size)
            except Exception as e:  # noqa: BLE001
                log.warning("Cannot encode %s for batch, skipping: %s", photo, e)
                continue
            key = f"p{idx:05d}"
            request = _build_request_dict(b64, model_name)
            line = json.dumps({"key": key, "request": request}, ensure_ascii=False)
            line_bytes = len(line.encode("utf-8")) + 1  # +1 for '\n'
            if total_bytes + line_bytes > MAX_PAYLOAD_BYTES:
                raise ValueError(
                    f"JSONL payload would exceed {MAX_PAYLOAD_BYTES} bytes at photo "
                    f"{idx}; caller must chunk smaller."
                )
            fh.write(line + "\n")
            total_bytes += line_bytes
            key_map.append((key, photo))
    log.info(
        "Built batch JSONL: %d photos, %.1f MB, model=%s → %s",
        len(key_map),
        total_bytes / 1_000_000,
        model_name,
        out_path,
    )
    return out_path, key_map, total_bytes


def _looks_like_tier_error(e: Exception) -> bool:
    s = str(e).lower()
    markers = (
        "permission_denied",
        "requires billing",
        "not enabled for batch",
        "batch api is not",
        "tier",
        "billing",
    )
    return any(m in s for m in markers)


def submit_batch(
    jsonl_path: Path,
    api_key: str,
    model: str = "lite",
    display_name: str = "Happy Vision batch",
) -> BatchSubmitResult:
    """Upload JSONL → create batch. Returns BatchSubmitResult.

    Raises TierRequiredError on detected free-tier rejection."""
    client = genai.Client(api_key=api_key)
    model_name = MODEL_MAP.get(model, MODEL_MAP["lite"])

    log.info("Uploading batch JSONL: %s", jsonl_path)
    # Per cookbook (google-gemini/cookbook Batch_mode.ipynb) the canonical
    # mime_type for batch input files is the short form "jsonl". Some SDK
    # builds (issue googleapis/python-genai#1590) mis-parse the upload
    # response when "application/jsonl" is sent, surfacing KeyError('file');
    # "text/plain" is the documented fallback in that issue.
    uploaded = None
    upload_errors: list[str] = []
    for attempt_mime in ("jsonl", "text/plain"):
        try:
            uploaded = client.files.upload(
                file=str(jsonl_path),
                config=types.UploadFileConfig(mime_type=attempt_mime),
            )
            break
        except KeyError as e:
            upload_errors.append(f"{attempt_mime}: KeyError {e}")
            continue
        except Exception as e:
            if _looks_like_tier_error(e):
                raise TierRequiredError() from e
            upload_errors.append(f"{attempt_mime}: {e}")
            # Retry with next mime type only on plausible upload-parser issues
            if "file" in str(e).lower() or "mime" in str(e).lower():
                continue
            raise
    if uploaded is None:
        raise RuntimeError(
            "Failed to upload batch JSONL after trying mime_types jsonl/text/plain: "
            + " | ".join(upload_errors)
        )

    log.info("Uploaded as %s (size=%s). Creating batch job...", uploaded.name, getattr(uploaded, "size_bytes", "?"))
    try:
        job = client.batches.create(
            model=model_name,
            src=uploaded.name,
            config=types.CreateBatchJobConfig(display_name=display_name),
        )
    except Exception as e:
        if _looks_like_tier_error(e):
            raise TierRequiredError() from e
        raise

    payload_bytes = int(getattr(uploaded, "size_bytes", 0) or 0)
    photo_count = 0
    # job.model_metadata might hold counts; we trust the caller's key_map len.
    log.info("Batch job created: %s (state=%s)", job.name, getattr(job.state, "name", job.state))
    return BatchSubmitResult(
        job_id=job.name,
        input_file_id=uploaded.name,
        photo_count=photo_count,
        payload_bytes=payload_bytes,
    )


def get_job_state(job_id: str, api_key: str) -> dict:
    """Poll one batch job. Returns {state, output_file, error}.

    state is the JobState enum name (e.g. 'JOB_STATE_RUNNING').
    output_file is the Files API name holding results, set once SUCCEEDED."""
    client = genai.Client(api_key=api_key)
    job = client.batches.get(name=job_id)
    state_name = job.state.name if hasattr(job.state, "name") else str(job.state)

    output_file = None
    dest = getattr(job, "dest", None)
    if dest is not None:
        output_file = getattr(dest, "file_name", None) or getattr(dest, "fileName", None)

    err = getattr(job, "error", None)
    err_msg = None
    if err is not None:
        err_msg = getattr(err, "message", None) or str(err)

    return {
        "state": state_name,
        "output_file": output_file,
        "error": err_msg,
    }


def _extract_usage_from_response_dict(resp: dict, model_name: str) -> dict:
    """Pull token counts out of a parsed batch response JSON object."""
    meta = resp.get("usage_metadata") or resp.get("usageMetadata") or {}
    input_tokens = int(meta.get("prompt_token_count") or meta.get("promptTokenCount") or 0)
    output_tokens = int(meta.get("candidates_token_count") or meta.get("candidatesTokenCount") or 0)
    total = int(meta.get("total_token_count") or meta.get("totalTokenCount") or (input_tokens + output_tokens))
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total,
        "model": model_name,
    }


def _extract_text_from_response_dict(resp: dict) -> str | None:
    """Pull the first text candidate out of a batch GenerateContentResponse."""
    candidates = resp.get("candidates") or []
    if not candidates:
        return None
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    for part in parts:
        text = part.get("text")
        if text:
            return text
    return None


def fetch_results(
    job_id: str,
    api_key: str,
    model: str = "lite",
) -> Iterator[BatchItemResult]:
    """Download output JSONL and yield BatchItemResult per line.

    The output format is one JSON object per line, each with:
        {"key": "p00001", "response": {...GenerateContentResponse...}}
    or
        {"key": "p00001", "error": {"code": ..., "message": "..."}}

    We lean on parse_response() from gemini_vision for consistency with the
    realtime path, so downstream code doesn't need to know the source.
    """
    client = genai.Client(api_key=api_key)
    job = client.batches.get(name=job_id)
    dest = getattr(job, "dest", None)
    output_file_name = None
    if dest is not None:
        output_file_name = getattr(dest, "file_name", None) or getattr(dest, "fileName", None)
    if not output_file_name:
        raise RuntimeError(f"Batch job {job_id} has no output file (state={job.state.name})")

    model_name = MODEL_MAP.get(model, MODEL_MAP["lite"])
    raw = client.files.download(file=output_file_name)
    # raw is bytes
    text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
    for line_no, line in enumerate(io.StringIO(text), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            log.warning("batch output line %d invalid JSON: %s", line_no, e)
            continue
        key = obj.get("key") or f"_line{line_no}"
        if "error" in obj and obj["error"]:
            err = obj["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            yield BatchItemResult(key=key, result=None, usage=None, error=msg or "batch error")
            continue
        resp = obj.get("response")
        if not isinstance(resp, dict):
            yield BatchItemResult(key=key, result=None, usage=None, error="missing response")
            continue
        text_payload = _extract_text_from_response_dict(resp)
        if not text_payload:
            yield BatchItemResult(key=key, result=None, usage=None, error="empty response text")
            continue
        parsed = parse_response(text_payload)
        if parsed is None:
            yield BatchItemResult(key=key, result=None, usage=None, error="unparseable response")
            continue
        usage = _extract_usage_from_response_dict(resp, model_name)
        yield BatchItemResult(key=key, result=parsed, usage=usage, error=None)


def cancel_job(job_id: str, api_key: str) -> bool:
    """Cancel a running batch job. Returns True on success."""
    client = genai.Client(api_key=api_key)
    try:
        client.batches.cancel(name=job_id)
        log.info("Cancelled batch job %s", job_id)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("Failed to cancel batch job %s: %s", job_id, e)
        return False


def estimate_completion_at(created_at_iso: str, slo_hours: int = 24) -> str:
    """Return ISO timestamp for when the job should complete per SLO."""
    from datetime import datetime, timedelta

    try:
        created = datetime.fromisoformat(created_at_iso)
    except ValueError:
        created = datetime.now()
    return (created + timedelta(hours=slo_hours)).isoformat()


def chunk_photos(photos: list[str], chunk_size: int = MAX_PHOTOS_PER_BATCH) -> list[list[str]]:
    """Split a photo list into batch-sized chunks."""
    return [photos[i:i + chunk_size] for i in range(0, len(photos), chunk_size)]


__all__ = [
    "BILLING_URL",
    "BatchItemResult",
    "BatchSubmitResult",
    "MAX_PAYLOAD_BYTES",
    "MAX_PHOTOS_PER_BATCH",
    "TierRequiredError",
    "build_jsonl_for_chunk",
    "cancel_job",
    "chunk_photos",
    "estimate_completion_at",
    "fetch_results",
    "get_job_state",
    "submit_batch",
]
