"""tests/test_report_generator.py"""

import csv
import json
from pathlib import Path

from modules.report_generator import generate_csv, generate_json


def _sample_results():
    return [
        {
            "file_path": "/photos/IMG_001.jpg",
            "title": "Speaker on stage",
            "description": "A keynote speaker.",
            "keywords": ["conference", "keynote"],
            "category": "ceremony",
            "subcategory": "keynote",
            "scene_type": "indoor",
            "mood": "formal",
            "people_count": 50,
            "identified_people": ["Jensen Huang"],
            "ocr_text": ["INOUT"],
        },
        {
            "file_path": "/photos/IMG_002.jpg",
            "title": "Networking session",
            "description": "Attendees mingling.",
            "keywords": ["networking"],
            "category": "networking",
            "subcategory": "",
            "scene_type": "indoor",
            "mood": "casual",
            "people_count": 20,
            "identified_people": [],
            "ocr_text": [],
        },
    ]


def test_generate_csv(tmp_path):
    output = tmp_path / "report.csv"
    generate_csv(_sample_results(), output)
    assert output.exists()

    with open(output, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 2
    assert rows[0]["title"] == "Speaker on stage"
    assert rows[0]["file_path"] == "/photos/IMG_001.jpg"
    assert "conference" in rows[0]["keywords"]


def test_generate_json(tmp_path):
    output = tmp_path / "report.json"
    generate_json(_sample_results(), output)
    assert output.exists()

    with open(output, encoding="utf-8") as f:
        data = json.load(f)

    assert len(data) == 2
    assert data[0]["title"] == "Speaker on stage"
    assert data[1]["keywords"] == ["networking"]


def test_generate_csv_empty(tmp_path):
    output = tmp_path / "empty.csv"
    generate_csv([], output)
    assert output.exists()
    content = output.read_text()
    lines = content.strip().split("\n")
    assert len(lines) == 1  # header only
