"""tests/test_metadata_writer.py"""

from modules.metadata_writer import (
    build_exiftool_args,
    write_metadata,
    read_metadata,
    has_happy_vision_tag,
)


def test_build_exiftool_args_basic():
    result = {
        "title": "Speaker on stage",
        "description": "A keynote speaker addresses the audience.",
        "keywords": ["conference", "keynote"],
        "category": "ceremony",
        "mood": "formal",
        "ocr_text": ["INOUT Creative"],
        "identified_people": ["Jensen Huang"],
    }
    args = build_exiftool_args(result)
    assert "-IPTC:Headline=Speaker on stage" in args
    assert "-IPTC:Caption-Abstract=A keynote speaker addresses the audience." in args
    assert "-IPTC:Keywords=conference" in args
    assert "-IPTC:Keywords=keynote" in args
    assert "-IPTC:Keywords=Jensen Huang" in args
    assert "-XMP:Category=ceremony" in args
    assert "-XMP:Scene=formal" in args
    assert any("INOUT Creative" in a for a in args)
    assert any("HappyVision" in a for a in args)


def test_build_exiftool_args_empty_fields():
    result = {
        "title": "",
        "description": "",
        "keywords": [],
        "category": "",
        "mood": "",
        "ocr_text": [],
        "identified_people": [],
    }
    args = build_exiftool_args(result)
    assert any("HappyVision" in a for a in args)


def test_build_exiftool_args_people_added_to_keywords():
    result = {
        "title": "CEO speech",
        "description": "CEO gives speech",
        "keywords": ["speech"],
        "category": "ceremony",
        "mood": "formal",
        "ocr_text": [],
        "identified_people": ["Jensen Huang", "Lisa Su"],
    }
    args = build_exiftool_args(result)
    keyword_args = [a for a in args if a.startswith("-IPTC:Keywords=")]
    keyword_values = [a.split("=", 1)[1] for a in keyword_args]
    assert "Jensen Huang" in keyword_values
    assert "Lisa Su" in keyword_values
    assert "speech" in keyword_values
