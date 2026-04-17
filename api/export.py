"""api/export.py — Report download"""

import json
import tempfile
import zipfile
from pathlib import Path

from flask import Blueprint, send_file

from modules.config import get_config_dir, load_config
from modules.event_store import EventStore
from modules.result_store import ResultStore
from modules.report_generator import generate_csv, generate_json

export_bp = Blueprint("export", __name__, url_prefix="/api/export")


@export_bp.route("/<fmt>")
def export_report(fmt):
    with ResultStore() as store:
        results = store.get_all_results()

    if not results:
        return {"error": "No results to export"}, 404

    tmp = Path(tempfile.mkdtemp())

    if fmt == "csv":
        path = tmp / "happy_vision_report.csv"
        generate_csv(results, path)
        return send_file(path, as_attachment=True, download_name="happy_vision_report.csv")
    elif fmt == "json":
        path = tmp / "happy_vision_report.json"
        generate_json(results, path)
        return send_file(path, as_attachment=True, download_name="happy_vision_report.json")
    else:
        return {"error": f"Unknown format: {fmt}"}, 400


@export_bp.route("/diagnostics")
def export_diagnostics():
    tmp = Path(tempfile.mkdtemp())
    bundle = tmp / "happy_vision_diagnostics.zip"
    config_dir = get_config_dir()

    config = dict(load_config())
    if config.get("gemini_api_key"):
        config["gemini_api_key"] = "***redacted***"

    with EventStore() as events:
        recent_events = events.get_recent(limit=200)

    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("config.json", json.dumps(config, ensure_ascii=False, indent=2))
        zf.writestr("events.json", json.dumps(recent_events, ensure_ascii=False, indent=2))

        results_db = config_dir / "results.db"
        if results_db.exists():
            zf.write(results_db, arcname="results.db")

        events_db = config_dir / "events.db"
        if events_db.exists():
            zf.write(events_db, arcname="events.db")

        logs_dir = config_dir / "logs"
        if logs_dir.exists():
            for log_file in sorted(logs_dir.glob("*.log"))[-7:]:
                zf.write(log_file, arcname=f"logs/{log_file.name}")

    return send_file(
        bundle,
        as_attachment=True,
        download_name="happy_vision_diagnostics.zip",
    )
