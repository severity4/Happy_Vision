"""Happy Vision — Web UI entry point"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, Response, jsonify, request, send_file, send_from_directory  # noqa: E402

from api.analysis import analysis_bp
from api.export import export_bp
from api.results import results_bp
from api.settings import settings_bp
from api.system import system_bp
from api.update import update_bp
from api.watch import watch_bp, auto_start_watcher
from modules.auth import SESSION_TOKEN, is_request_allowed  # noqa: E402

_allowed_roots: set[Path] = set()


def register_allowed_root(folder) -> None:
    """Mark a folder as legitimately browseable/servable. Called whenever the
    user explicitly opens a folder for watching or analysis."""
    p = Path(folder).expanduser().resolve()
    if p.is_dir():
        _allowed_roots.add(p)


def _path_is_allowed(path: Path) -> bool:
    """Check if a resolved path is inside the user's home OR an allowed root."""
    try:
        resolved = path.expanduser().resolve()
    except (OSError, RuntimeError):
        return False

    home = Path.home().resolve()
    try:
        resolved.relative_to(home)
        return True
    except ValueError:
        pass

    for root in _allowed_roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


app = Flask(__name__)


@app.before_request
def _check_auth():
    if not is_request_allowed(request):
        return jsonify({"error": "Forbidden"}), 403


# Register blueprints
app.register_blueprint(settings_bp)
app.register_blueprint(analysis_bp)
app.register_blueprint(results_bp)
app.register_blueprint(export_bp)
app.register_blueprint(watch_bp)
app.register_blueprint(update_bp)
app.register_blueprint(system_bp)


def _post_start_init() -> None:
    """Deferred initialization that touches Keychain + config.

    At module-import time in a frozen --windowed .app this deadlocks: macOS
    Keychain wants to show a permission prompt for a new binary signature,
    but no GUI is up yet to display it. We run this after pywebview has
    surfaced its window (bundled path) or immediately (dev). secret_store
    also caps each Keychain call with a 2s timeout as a belt-and-braces."""
    from modules.config import load_config
    from modules import rate_limiter
    cfg = load_config()
    if cfg.get("watch_folder"):
        register_allowed_root(cfg["watch_folder"])
    # Apply user's throughput settings (v0.5.1+). Default is still 60 RPM if
    # the key is absent from old configs.
    rate_limiter.configure(int(cfg.get("rate_limit_rpm", 60)))
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        try:
            auto_start_watcher()
        except Exception:
            # Don't kill app start-up if the watcher can't spin up (bad folder,
            # keychain still not authorised, etc). User can retry from Settings.
            import logging
            logging.getLogger(__name__).exception("auto_start_watcher failed")


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
    if not _path_is_allowed(p):
        return jsonify({"error": "Forbidden"}), 403

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
    if not photo_path:
        return jsonify({"error": "Not found"}), 404
    p = Path(photo_path)
    if p.suffix.lower() not in {".jpg", ".jpeg"}:
        return jsonify({"error": "Not found"}), 404
    if not p.is_file():
        return jsonify({"error": "Not found"}), 404
    if not _path_is_allowed(p):
        return jsonify({"error": "Not found"}), 404
    return send_file(str(p), mimetype="image/jpeg")


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
        # Serve index.html with session token substitution
        index = (DIST_DIR / "index.html").read_text()
        return Response(
            index.replace("__HV_TOKEN__", SESSION_TOKEN),
            mimetype="text/html",
        )
    return {"message": "Happy Vision API is running. Frontend not built yet."}, 200


if __name__ == "__main__":
    is_frozen = getattr(sys, "frozen", False)
    if is_frozen:
        import threading
        import time
        import webview

        # Start Flask in background thread. Post-start init (Keychain + watcher)
        # runs inside the thread, with a small delay so pywebview's window is
        # visible to receive any macOS Keychain permission prompt.
        def _run_flask():
            time.sleep(0.8)
            _post_start_init()
            app.run(host="127.0.0.1", port=8081, debug=False)

        threading.Thread(target=_run_flask, daemon=True).start()

        webview.create_window(
            f"Happy Vision v{_get_version()}",
            "http://127.0.0.1:8081",
            width=1200,
            height=800,
            min_size=(800, 600),
        )
        webview.start()
    else:
        _post_start_init()
        app.run(host="127.0.0.1", port=8081, debug=True)
