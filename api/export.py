"""api/export.py — Report download"""

import io
import json
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from modules.config import get_config_dir, load_config
from modules.event_store import EventStore
from modules.pdf_report import generate_report as generate_pdf
from modules.result_store import ResultStore
from modules.report_generator import generate_csv, generate_json

export_bp = Blueprint("export", __name__, url_prefix="/api/export")


def _downloads_dir() -> Path:
    """Resolve the export target folder.

    Precedence:
      1. `export_folder` in config (user-chosen via Settings); must be an
         existing directory we can write to. Falls through if the folder
         vanishes (e.g., external drive ejected).
      2. `~/Downloads` — created if absent.
    """
    cfg = load_config()
    user_dir = str(cfg.get("export_folder") or "").strip()
    if user_dir:
        p = Path(user_dir).expanduser()
        try:
            if p.is_dir():
                return p
        except OSError:
            pass  # unreadable → fall through
    d = Path.home() / "Downloads"
    d.mkdir(exist_ok=True)
    return d


def _stamped_name(prefix: str, ext: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{prefix}_{stamp}.{ext}"


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


# ---------------------------------------------------------------------------
# v0.13.2: save-to-Downloads endpoints for pywebview compatibility
#
# WKWebView (pywebview's backend on macOS) doesn't reliably trigger the
# browser-style download prompt for blob / attachment responses — clicking
# a <a download> link may just fail silently or navigate away with no way
# back. So we expose POST routes that write the report directly to the
# user's Downloads folder and return the path. The frontend shows a toast
# "已匯出到 ~/Downloads/..." — no navigation, no blob, no WKWebView
# download handler required.
# ---------------------------------------------------------------------------


def _save_bytes(data: bytes, filename: str) -> Path:
    out = _downloads_dir() / filename
    # Avoid clobbering: suffix -1, -2, ... if a same-name file already exists.
    if out.exists():
        stem, sep, ext = filename.rpartition(".")
        n = 1
        while True:
            candidate = _downloads_dir() / f"{stem}-{n}{sep}{ext}"
            if not candidate.exists():
                out = candidate
                break
            n += 1
    out.write_bytes(data)
    return out


@export_bp.route("/save/<fmt>", methods=["POST"])
def export_save(fmt):
    """Save report to ~/Downloads and return the saved path."""
    if fmt == "pdf":
        config = load_config()
        folder = config.get("watch_folder") or ""
        with ResultStore() as store:
            results = store.get_results_for_folder(folder) if folder else store.get_all_results()
        if not results:
            return jsonify({"error": "No results to export"}), 404
        pdf_bytes = generate_pdf(results, folder=folder or None)
        saved = _save_bytes(pdf_bytes, _stamped_name("happy_vision_report", "pdf"))
        return jsonify({"saved": str(saved)})

    if fmt in ("csv", "json"):
        with ResultStore() as store:
            results = store.get_all_results()
        if not results:
            return jsonify({"error": "No results to export"}), 404

        buf = io.StringIO()
        if fmt == "csv":
            # Reuse generate_csv via a temp path (it writes through a Path)
            tmp = Path(tempfile.mkdtemp()) / "r.csv"
            generate_csv(results, tmp)
            data = tmp.read_bytes()
            ext = "csv"
        else:
            tmp = Path(tempfile.mkdtemp()) / "r.json"
            generate_json(results, tmp)
            data = tmp.read_bytes()
            ext = "json"
        _ = buf  # placeholder; kept for structural symmetry
        saved = _save_bytes(data, _stamped_name("happy_vision_report", ext))
        return jsonify({"saved": str(saved)})

    if fmt == "diagnostics":
        tmp = Path(tempfile.mkdtemp())
        bundle_path = tmp / "diag.zip"
        config_dir = get_config_dir()

        config = dict(load_config())
        if config.get("gemini_api_key"):
            config["gemini_api_key"] = "***redacted***"

        with EventStore() as events:
            recent_events = events.get_recent(limit=200)

        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
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

        saved = _save_bytes(bundle_path.read_bytes(),
                            _stamped_name("happy_vision_diagnostics", "zip"))
        return jsonify({"saved": str(saved)})

    return jsonify({"error": f"Unknown format: {fmt}"}), 400
