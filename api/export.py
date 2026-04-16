"""api/export.py — Report download"""

import tempfile
from pathlib import Path

from flask import Blueprint, send_file

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
