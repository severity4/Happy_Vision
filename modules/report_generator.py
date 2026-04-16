"""modules/report_generator.py — CSV/JSON report export"""

import csv
import json
from pathlib import Path

from modules.logger import setup_logger

log = setup_logger("report_generator")

CSV_FIELDS = [
    "file_path",
    "title",
    "description",
    "keywords",
    "category",
    "subcategory",
    "scene_type",
    "mood",
    "people_count",
    "identified_people",
    "ocr_text",
]


def generate_csv(results: list[dict], output_path: Path | str) -> None:
    """Generate a CSV report from analysis results."""
    output_path = Path(output_path)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for result in results:
            row = dict(result)
            for key in ["keywords", "identified_people", "ocr_text"]:
                if isinstance(row.get(key), list):
                    row[key] = ", ".join(row[key])
            writer.writerow(row)
    log.info("CSV report written to %s (%d photos)", output_path, len(results))


def generate_json(results: list[dict], output_path: Path | str) -> None:
    """Generate a JSON report from analysis results."""
    output_path = Path(output_path)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    log.info("JSON report written to %s (%d photos)", output_path, len(results))
