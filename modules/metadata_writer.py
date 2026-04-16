"""modules/metadata_writer.py — IPTC/XMP metadata read/write via exiftool"""

import json
import os
import subprocess
import sys
from pathlib import Path

from modules.logger import setup_logger

log = setup_logger("metadata_writer")


def _get_exiftool_cmd() -> str:
    """Find exiftool binary, checking PyInstaller bundle first."""
    if getattr(sys, "frozen", False):
        bundled = Path(sys._MEIPASS) / "exiftool"
        if bundled.exists():
            return str(bundled)
    return "exiftool"


def build_exiftool_args(result: dict) -> list[str]:
    """Build exiftool CLI arguments from an analysis result dict."""
    args = []

    if result.get("title"):
        args.append(f"-IPTC:Headline={result['title']}")
        args.append(f"-XMP:Title={result['title']}")

    if result.get("description"):
        args.append(f"-IPTC:Caption-Abstract={result['description']}")
        args.append(f"-XMP:Description={result['description']}")

    all_keywords = list(result.get("keywords", []))
    for person in result.get("identified_people", []):
        if person not in all_keywords:
            all_keywords.append(person)
    for kw in all_keywords:
        args.append(f"-IPTC:Keywords={kw}")
        args.append(f"-XMP:Subject={kw}")

    if result.get("category"):
        args.append(f"-XMP:Category={result['category']}")

    if result.get("mood"):
        args.append(f"-XMP:Scene={result['mood']}")

    if result.get("ocr_text"):
        ocr_combined = " | ".join(result["ocr_text"])
        args.append(f"-XMP:Comment={ocr_combined}")

    args.append("-XMP-xmp:Instructions=HappyVisionProcessed")

    return args


def write_metadata(photo_path: str, result: dict, backup: bool = True) -> bool:
    """Write analysis result as IPTC/XMP metadata into a photo file."""
    path = Path(photo_path)
    if not path.exists():
        log.error("File not found: %s", photo_path)
        return False

    args = build_exiftool_args(result)
    if not args:
        return True

    cmd = [_get_exiftool_cmd()]
    if not backup:
        cmd.append("-overwrite_original")
    cmd.extend(args)
    cmd.append(str(path))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            log.error("exiftool failed for %s: %s", photo_path, proc.stderr)
            return False
        log.info("Metadata written to %s", path.name)
        return True
    except subprocess.TimeoutExpired:
        log.error("exiftool timed out for %s", photo_path)
        return False
    except FileNotFoundError:
        log.error("exiftool not found. Install with: brew install exiftool")
        return False


def read_metadata(photo_path: str) -> dict:
    """Read existing IPTC/XMP metadata from a photo."""
    try:
        proc = subprocess.run(
            [_get_exiftool_cmd(), "-json", "-IPTC:all", "-XMP:all", str(photo_path)],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            return data[0] if data else {}
    except Exception as e:
        log.error("Failed to read metadata from %s: %s", photo_path, e)
    return {}


def has_happy_vision_tag(photo_path: str) -> bool:
    """Check if a photo has already been processed by Happy Vision."""
    metadata = read_metadata(photo_path)
    instructions = metadata.get("Instructions", "")
    return "HappyVisionProcessed" in str(instructions)
