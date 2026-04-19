"""modules/gemini_vision.py — Gemini API photo analysis"""

import io
import json
import threading
import time
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image, UnidentifiedImageError

from modules.logger import setup_logger
# IMPORTANT: import the module, not the attribute — `configure()` swaps the
# attribute at runtime and this keeps us binding to the current instance.
from modules import rate_limiter

log = setup_logger("gemini_vision")


class InvalidAPIKeyError(Exception):
    """Gemini rejected the API key (401 / API_KEY_INVALID / UNAUTHENTICATED /
    PERMISSION_DENIED). Retrying won't help — the whole batch should halt
    so the user can fix their key instead of churning through N photos
    that would all fail identically."""


# Substrings in the error message that unambiguously mean "the key is bad".
# Kept narrow on purpose: matching just "401" would false-positive on error
# descriptions that happen to contain that number.
_AUTH_FATAL_MARKERS = (
    "API_KEY_INVALID",
    "API key not valid",
    "UNAUTHENTICATED",
    "PERMISSION_DENIED",
)


# Module-level cache: one genai.Client per api_key, reused across calls.
_client_cache: dict[str, genai.Client] = {}
_client_cache_lock = threading.Lock()


def _get_client(api_key: str) -> genai.Client:
    with _client_cache_lock:
        client = _client_cache.get(api_key)
        if client is None:
            client = genai.Client(api_key=api_key)
            _client_cache[api_key] = client
        return client


MODEL_MAP = {
    "lite": "gemini-2.5-flash-lite",
    "flash": "gemini-2.5-flash",
}

# Max long edge before sending to Gemini. Configurable at call time via
# analyze_photo(max_size=...); the default 3072 matches the AnyVision baseline
# and preserves description fidelity. Users can drop to 1536 / 1024 for
# ~4x / ~9x fewer image input tokens at the cost of some detail.
DEFAULT_MAX_IMAGE_SIZE = 3072

# Disable all safety filters to avoid false blocks on event photos
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
]

CATEGORY_ENUM = [
    "ceremony", "reception", "panel", "performance", "networking",
    "portrait", "venue", "branding", "backstage", "registration",
    "workshop", "exhibition", "press", "award", "other",
]

MOOD_ENUM = [
    "formal", "casual", "energetic", "intimate", "celebratory",
    "serious", "relaxed", "professional", "festive", "neutral",
]

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Short English title describing the main subject/action"},
        "description": {"type": "string", "description": "Detailed English description of the photo"},
        "keywords": {"type": "array", "items": {"type": "string"}, "description": "English keywords/tags"},
        "category": {"type": "string", "enum": CATEGORY_ENUM},
        "subcategory": {"type": "string", "description": "Subcategory within the main category"},
        "scene_type": {"type": "string", "enum": ["indoor", "outdoor", "studio"]},
        "mood": {"type": "string", "enum": MOOD_ENUM},
        "people_count": {"type": "integer", "description": "Approximate number of people visible"},
        "identified_people": {"type": "array", "items": {"type": "string"}, "description": "Names of recognized public figures"},
        "ocr_text": {"type": "array", "items": {"type": "string"}, "description": "Text visible in the photo (signs, banners, slides)"},
    },
    "required": ["title", "description", "keywords", "category", "scene_type", "mood", "people_count"],
}


def build_prompt() -> str:
    return """Analyze this event photo and provide structured metadata in English.

You are a professional event photographer's assistant. Describe what you see accurately and concisely.

Requirements:
- title: One concise English sentence describing the main subject/action
- description: 2-3 English sentences with specific details (setting, people, actions, lighting)
- keywords: 5-15 relevant English tags for searchability
- category: Main event category
- subcategory: More specific type within the category
- scene_type: indoor, outdoor, or studio
- mood: Overall atmosphere
- people_count: Approximate number of people visible
- identified_people: If you recognize any public figures (celebrities, business leaders, politicians), list their full names. Only include people you are confident about. If you cannot identify anyone or are unsure, return an empty array.
- ocr_text: Any readable text in the photo (signs, banners, projected slides, name tags)

Respond ONLY with valid JSON matching the required schema."""


def resize_for_api(photo_bytes: bytes, max_size: int = DEFAULT_MAX_IMAGE_SIZE) -> bytes:
    """Resize photo so the long edge is at most max_size pixels.

    ALWAYS returns JPEG bytes — even if the input is a PNG / TIFF / HEIC
    file that's been renamed to `.jpg`, or a genuine JPG that doesn't need
    resizing. This guarantees the `mime_type="image/jpeg"` tag we hand to
    Gemini matches the payload; otherwise a PNG-labelled-as-JPEG would
    silently fail (or worse, get miscategorized by the API)."""
    img = Image.open(io.BytesIO(photo_bytes))
    w, h = img.size

    # Fast path: a small, already-JPEG input needs no work. PIL exposes the
    # original format via img.format — "JPEG" is the only string we short-
    # circuit on, and RGBA mode (which JPEG can't express natively) is
    # excluded so we never smuggle out a non-JPEG payload.
    if max(w, h) <= max_size and img.format == "JPEG" and img.mode in ("RGB", "L"):
        return photo_bytes

    # Compute target size (no-op if already within max_size — we still
    # re-encode below to normalize format to JPEG).
    if max(w, h) > max_size:
        if w >= h:
            new_w = max_size
            new_h = int(h * max_size / w)
        else:
            new_h = max_size
            new_w = int(w * max_size / h)
        img = img.resize((new_w, new_h), Image.LANCZOS)
    else:
        new_w, new_h = w, h

    # JPEG can't encode alpha. Flatten RGBA / LA onto a white background
    # rather than raising OSError — losing transparency is the lesser evil
    # for photo analysis, and matches what most editors do on export.
    if img.mode in ("RGBA", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        mask = img.split()[-1]  # alpha channel
        background.paste(img.convert("RGB"), mask=mask)
        img = background
    elif img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    original_kb = len(photo_bytes) / 1024
    resized_kb = buf.tell() / 1024
    log.debug("Normalized %dx%d → %dx%d (%.0fKB → %.0fKB)",
              w, h, new_w, new_h, original_kb, resized_kb)
    return buf.getvalue()


def parse_response(raw_text: str | None) -> dict | None:
    """Parse Gemini response, filling in defaults for missing fields.

    Safety filter or SDK drift can hand us `None` instead of text (full
    block) or a bare list / scalar (schema miss). Return None in all
    non-dict cases rather than raising — the caller treats None as
    "photo failed" and carries on."""
    if not raw_text or not isinstance(raw_text, str):
        return None

    try:
        text = raw_text.strip()
        if not text:
            return None
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        data = json.loads(text)
    except (json.JSONDecodeError, IndexError, ValueError, AttributeError):
        return None

    # Guard: schema enforcement is best-effort. A list / string / None at
    # the root would crash the defaults loop below with TypeError — treat
    # it as "unusable response" instead.
    if not isinstance(data, dict):
        return None

    defaults = {
        "title": "",
        "description": "",
        "keywords": [],
        "category": "",
        "subcategory": "",
        "scene_type": "",
        "mood": "",
        "people_count": 0,
        "identified_people": [],
        "ocr_text": [],
    }
    for key, default in defaults.items():
        if key not in data:
            data[key] = default
    return data


def _extract_usage(response, model_name: str) -> dict:
    """Pull token counts from response.usage_metadata. Safe to zeros if absent."""
    meta = getattr(response, "usage_metadata", None)
    input_tokens = int(getattr(meta, "prompt_token_count", 0) or 0)
    output_tokens = int(getattr(meta, "candidates_token_count", 0) or 0)
    total = int(getattr(meta, "total_token_count", 0) or (input_tokens + output_tokens))
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total,
        "model": model_name,
    }


def analyze_photo(
    photo_path: str,
    api_key: str,
    model: str = "lite",
    max_retries: int = 3,
    max_size: int = DEFAULT_MAX_IMAGE_SIZE,
) -> tuple[dict | None, dict | None]:
    """Analyze a single photo with Gemini API.

    `max_size` is the long-edge pixel cap sent to Gemini after resize. Smaller
    = fewer image tiles = cheaper and faster, at the cost of some description
    detail. Callers typically read this from config.image_max_size.

    Returns (parsed_result, usage) on success, (None, None) on failure.
    `usage` is {"input_tokens", "output_tokens", "total_tokens", "model"}.
    """
    model_name = MODEL_MAP.get(model, MODEL_MAP["lite"])

    # Read + decode BEFORE touching Gemini. A corrupt/0-byte/truncated
    # JPG would otherwise crash the worker thread because PIL raises
    # UnidentifiedImageError (or OSError on truncation) inside resize_for_api,
    # which then propagates via future.result() and kills the whole batch.
    # Guard at the boundary so one bad file skips cleanly.
    try:
        photo_bytes = Path(photo_path).read_bytes()
    except OSError as e:
        log.error("Cannot read %s: %s", photo_path, e)
        return None, None

    try:
        photo_bytes = resize_for_api(photo_bytes, max_size=max_size)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        log.warning("Corrupt or unreadable image %s (%s); skipping",
                    photo_path, type(e).__name__)
        return None, None

    prompt = build_prompt()

    client = _get_client(api_key)

    # Global rate limit (shared by pipeline workers and folder watcher).
    # 60s cap lets cancel/shutdown propagate instead of blocking forever if
    # the token bucket is misconfigured or contended beyond patience.
    # Read `default_limiter` via the module so runtime `configure()` swaps
    # take effect on subsequent calls.
    if not rate_limiter.default_limiter.acquire(timeout=60):
        log.warning("Rate limiter timeout for %s — giving up", photo_path)
        return None, None

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[
                    types.Content(
                        parts=[
                            types.Part.from_bytes(data=photo_bytes, mime_type="image/jpeg"),
                            types.Part.from_text(text=prompt),
                        ]
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                    response_schema=ANALYSIS_SCHEMA,
                    safety_settings=[
                        types.SafetySetting(category=s["category"], threshold=s["threshold"])
                        for s in SAFETY_SETTINGS
                    ],
                ),
            )
            result = parse_response(response.text)
            if result:
                usage = _extract_usage(response, model_name)
                log.info("Analyzed %s: %s (tokens: %d in, %d out)",
                         Path(photo_path).name, result.get("title", ""),
                         usage["input_tokens"], usage["output_tokens"])
                return result, usage
            log.warning("Failed to parse response for %s", photo_path)
            return None, None

        except InvalidAPIKeyError:
            # Already classified as fatal — re-raise so pipeline can halt.
            raise
        except Exception as e:
            error_str = str(e)
            # Auth / permission failures are terminal: retrying with the same
            # bad key just burns time. Signal the caller (pipeline) to stop
            # the whole batch rather than returning (None, None) — which
            # would cause us to keep calling Gemini for each remaining photo.
            if any(m in error_str for m in _AUTH_FATAL_MARKERS):
                log.error("Fatal auth error for %s (halting batch): %s",
                          photo_path, error_str)
                raise InvalidAPIKeyError(error_str) from e
            retryable_markers = (
                "429", "500", "502", "503", "504",
                "DEADLINE_EXCEEDED", "RESOURCE_EXHAUSTED",
                "UNAVAILABLE", "INTERNAL",
                # Network / DNS / socket transients. Offline wifi,
                # firewall blip, VPN re-handshake — transient, retry
                # rather than hard-failing the photo on first touch.
                # Lowercase checked below with a second `in` via .lower()
                # since socket error strings vary by platform (macOS
                # "getaddrinfo failed", Linux "Name or service not known").
                "getaddrinfo",
                "Name or service not known",
                "Temporary failure in name resolution",
                "Could not resolve host",
                "Connection refused",
                "Connection reset",
                "Max retries exceeded",
                "timed out",
                "Network is unreachable",
            )
            if any(m in error_str for m in retryable_markers):
                wait = 2 ** attempt
                log.warning("Retryable API error for %s (attempt %d/%d), retry in %ds: %s",
                            photo_path, attempt + 1, max_retries, wait, error_str)
                time.sleep(wait)
                continue
            log.error("API error for %s: %s", photo_path, error_str)
            return None, None

    log.error("All retries exhausted for %s", photo_path)
    return None, None
