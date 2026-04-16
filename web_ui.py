"""Happy Vision — Web UI entry point"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, send_file, send_from_directory  # noqa: E402

from api.analysis import analysis_bp
from api.export import export_bp
from api.results import results_bp
from api.settings import settings_bp

app = Flask(__name__)

# Register blueprints
app.register_blueprint(settings_bp)
app.register_blueprint(analysis_bp)
app.register_blueprint(results_bp)
app.register_blueprint(export_bp)


@app.route("/api/health")
def health():
    return {"status": "ok"}


@app.route("/api/photo")
def serve_photo():
    """Serve a photo file by path (for thumbnail display in frontend)."""
    photo_path = request.args.get("path", "")
    if not photo_path or not Path(photo_path).is_file():
        return {"error": "File not found"}, 404
    return send_file(photo_path, mimetype="image/jpeg")


# Serve Vue frontend in production
DIST_DIR = Path(__file__).parent / "frontend" / "dist"


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
    app.run(host="0.0.0.0", port=8081, debug=True)
