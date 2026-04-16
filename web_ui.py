"""Happy Vision — Web UI entry point"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, request, send_file, send_from_directory  # noqa: E402

from api.analysis import analysis_bp
from api.export import export_bp
from api.results import results_bp
from api.settings import settings_bp
from api.update import update_bp
from api.watch import watch_bp, auto_start_watcher

app = Flask(__name__)

# Register blueprints
app.register_blueprint(settings_bp)
app.register_blueprint(analysis_bp)
app.register_blueprint(results_bp)
app.register_blueprint(export_bp)
app.register_blueprint(watch_bp)
app.register_blueprint(update_bp)

# Auto-start watch folder if previously enabled
auto_start_watcher()


def _get_version() -> str:
    version_file = _get_bundle_dir() / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "dev"


@app.route("/api/health")
def health():
    return {"status": "ok", "version": _get_version()}


@app.route("/api/browse")
def browse_folder():
    """Browse filesystem folders for the folder picker UI."""
    folder = request.args.get("path", str(Path.home()))
    p = Path(folder)
    if not p.is_dir():
        return jsonify({"error": "Not a directory"}), 400

    items = []
    try:
        for child in sorted(p.iterdir()):
            if child.name.startswith("."):
                continue
            if child.is_dir():
                items.append({"name": child.name, "path": str(child), "type": "folder"})
            elif child.suffix.lower() in {".jpg", ".jpeg"}:
                items.append({"name": child.name, "path": str(child), "type": "photo"})
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403

    photo_count = sum(1 for i in items if i["type"] == "photo")
    return jsonify({
        "current": str(p),
        "parent": str(p.parent) if p != p.parent else None,
        "items": items,
        "photo_count": photo_count,
    })


@app.route("/api/photo")
def serve_photo():
    """Serve a photo file by path (for thumbnail display in frontend)."""
    photo_path = request.args.get("path", "")
    if not photo_path or not Path(photo_path).is_file():
        return {"error": "File not found"}, 404
    return send_file(photo_path, mimetype="image/jpeg")


# Serve Vue frontend in production
# PyInstaller sets sys._MEIPASS to the temp directory where bundled files are extracted
def _get_bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


DIST_DIR = _get_bundle_dir() / "frontend" / "dist"


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    if DIST_DIR.exists():
        file_path = DIST_DIR / path
        if file_path.is_file():
            return send_from_directory(DIST_DIR, path)
        return send_from_directory(DIST_DIR, "index.html")
    return {"message": "Happy Vision API is running. Frontend not built yet."}, 200


if __name__ == "__main__":
    is_frozen = getattr(sys, "frozen", False)
    if is_frozen:
        import threading
        import webview

        # Start Flask in background thread
        threading.Thread(
            target=lambda: app.run(host="127.0.0.1", port=8081, debug=False),
            daemon=True,
        ).start()

        # Open native window
        webview.create_window(
            f"Happy Vision v{_get_version()}",
            "http://127.0.0.1:8081",
            width=1200,
            height=800,
            min_size=(800, 600),
        )
        webview.start()
    else:
        app.run(host="127.0.0.1", port=8081, debug=True)
