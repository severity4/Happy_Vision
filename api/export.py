"""api/export.py — Report download"""

import io
import json
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from flask import Blueprint, send_file

from modules.config import get_config_dir, load_config
from modules.event_store import EventStore
from modules.pdf_report import generate_report as generate_pdf
from modules.result_store import ResultStore
from modules.report_generator import generate_csv, generate_json

export_bp = Blueprint("export", __name__, url_prefix="/api/export")


@export_bp.route("/<fmt>")
def export_report(fmt):
    if fmt == "pdf":
        # PDF uses the richer get_results_for_folder shape (includes _usage)
        config = load_config()
        folder = config.get("watch_folder") or ""
        with ResultStore() as store:
            if folder:
                results = store.get_results_for_folder(folder)
            else:
                results = store.get_all_results()
        if not results:
            return {"error": "No results to export"}, 404
        pdf_bytes = generate_pdf(results, folder=folder or None)
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"happy_vision_report_{stamp}.pdf",
        )

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
