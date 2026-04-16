"""tests/test_cli.py"""

import json
from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner

from cli import main


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Analyze photos" in result.output
    assert "--model" in result.output


def test_cli_no_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / ".hv"))
    (tmp_path / "photos").mkdir()
    (tmp_path / "photos" / "test.jpg").write_bytes(b"\xff\xd8")

    runner = CliRunner()
    result = runner.invoke(main, [str(tmp_path / "photos")])
    assert result.exit_code != 0
    assert "API key" in result.output or "api_key" in result.output.lower()


def test_cli_runs_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / ".hv"))

    config_dir = tmp_path / ".hv"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps({"gemini_api_key": "fake-key"}))

    (tmp_path / "photos").mkdir()
    (tmp_path / "photos" / "test.jpg").write_bytes(b"\xff\xd8")

    mock_result = {"title": "Test", "keywords": ["test"]}

    with patch("modules.pipeline.analyze_photo", return_value=mock_result):
        runner = CliRunner()
        result = runner.invoke(main, [
            str(tmp_path / "photos"),
            "--output", str(tmp_path / "output"),
        ])

    assert result.exit_code == 0
    assert "1" in result.output
