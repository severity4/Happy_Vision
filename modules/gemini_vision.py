"""modules/gemini_vision.py — Gemini API photo analysis"""

import io
import json
import time
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image

from modules.logger import setup_logger

log = setup_logger("gemini_vision")

MODEL_MAP = {
    "lite": "gemini-2.0-flash-lite",
    "flash": "gemini-2.5-flash-preview-05-20",
}

# Max long edge before sending to Gemini (matches AnyVision default)
MAX_IMAGE_SIZE = 3072

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


def resize_for_api(photo_bytes: bytes, max_size: int = MAX_IMAGE_SIZE) -> bytes:
    """Resize photo so the long edge is at most max_size pixels. Returns JPEG bytes."""
    img = Image.open(io.BytesIO(photo_bytes))
    w, h = img.size
    if max(w, h) <= max_size:
        return photo_bytes

    if w >= h:
        new_w = max_size
        new_h = int(h * max_size / w)
    else:
        new_h = max_size
        new_w = int(w * max_size / h)

    img = img.resize((new_w, new_h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    original_kb = len(photo_bytes) / 1024
    resized_kb = buf.tell() / 1024
    log.debug("Resized %dx%d → %dx%d (%.0fKB → %.0fKB)", w, h, new_w, new_h, original_kb, resized_kb)
    return buf.getvalue()


def parse_response(raw_text: str) -> dict | None:
    """Parse Gemini response, filling in defaults for missing fields."""
    try:
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        data = json.loads(text)
    except (json.JSONDecodeError, IndexError):
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


def analyze_photo(
    photo_path: str,
    api_key: str,
    model: str = "lite",
    max_retries: int = 3,
) -> dict | None:
    """Analyze a single photo with Gemini API. Returns parsed result or None on failure."""
    model_name = MODEL_MAP.get(model, MODEL_MAP["lite"])
    photo_bytes = Path(photo_path).read_bytes()
    photo_bytes = resize_for_api(photo_bytes)
    prompt = build_prompt()

    client = genai.Client(api_key=api_key)

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
                log.info("Analyzed %s: %s", Path(photo_path).name, result.get("title", ""))
                return result
            log.warning("Failed to parse response for %s", photo_path)
            return None

        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "500" in error_str or "503" in error_str:
                wait = 2 ** attempt
                log.warning("API error for %s (attempt %d/%d), retrying in %ds: %s",
                            photo_path, attempt + 1, max_retries, wait, error_str)
                time.sleep(wait)
                continue
            log.error("API error for %s: %s", photo_path, error_str)
            return None

    log.error("All retries exhausted for %s", photo_path)
    return None
