"""api/results.py — Query and edit analysis results"""

from pathlib import Path

from flask import Blueprint, request, jsonify

from modules.metadata_writer import write_metadata
from modules.result_store import ResultStore

results_bp = Blueprint("results", __name__, url_prefix="/api/results")


def _coerce_int(v, default: int) -> int:
    """Garbage-in-safe int parse. Same pattern as api/settings.py and
    api/batch.py — bad value returns the caller's default instead of
    letting Werkzeug blow up with a 500."""
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _folder_is_allowed(folder: str) -> bool:
    """Reuse the web_ui path allowlist (home + registered roots). v0.12.1
    closes the gap between v0.10.1's batch-endpoint hardening and the new
    v0.12.0 retry endpoints: a caller with the session token shouldn't be
    able to probe or DELETE failed rows under arbitrary paths."""
    if not folder:
        return True  # "no folder" = whole DB, allowed
    try:
        from web_ui import _path_is_allowed
    except ImportError:
        return False
    return _path_is_allowed(Path(folder))


@results_bp.route("", methods=["GET"])
def get_results():
    with ResultStore() as store:
        results = store.get_all_results()
        summary = store.get_summary()
    return jsonify({"results": results, "summary": summary})


@results_bp.route("/failed", methods=["GET"])
def list_failed():
    """List photos whose analysis failed, for the Monitor 'retry failed' UI.

    Optional query param `folder` restricts to one root. This is so the
    user can say "retry the 23 failures under LucidLink/WeddingA" without
    accidentally re-enqueuing failures from a different project.
    """
    folder = request.args.get("folder", "").strip() or None
    if folder and not _folder_is_allowed(folder):
        return jsonify({
            "error": "folder_not_allowed",
            "message": "此資料夾不在允許清單。",
        }), 403
    limit = max(1, min(5000, _coerce_int(request.args.get("limit"), 1000)))
    with ResultStore() as store:
        items = store.get_failed_results(folder=folder, limit=limit)
    return jsonify({"count": len(items), "items": items})


@results_bp.route("/retry", methods=["POST"])
def retry_failed():
    """Clear the 'failed' marker on the specified files so the next analysis
    run (realtime or batch, whatever the user has configured) picks them up.

    Client passes `{"file_paths": ["/a.jpg", "/b.jpg"]}` OR `{"folder": ".."}`
    to retry every failure under a folder. Returns count cleared + the
    folder the caller should kick off next (convenience so the UI can chain
    this into a submit or watch-enqueue call)."""
    data = request.get_json(silent=True) or {}
    file_paths = data.get("file_paths")
    folder = (data.get("folder") or "").strip() or None

    # Allowlist check on folder AND each file_path — caller with the
    # session token shouldn't be able to clear failure markers outside
    # paths they've legitimately opened (via settings, onboarding, or
    # /api/watch/start). Matches the v0.10.1 batch endpoint hardening.
    if folder and not _folder_is_allowed(folder):
        return jsonify({
            "error": "folder_not_allowed",
            "message": "此資料夾不在允許清單。",
        }), 403
    if file_paths:
        if not isinstance(file_paths, list):
            return jsonify({"error": "file_paths must be an array"}), 400
        bad = [p for p in file_paths if not _folder_is_allowed(str(Path(p).parent))]
        if bad:
            return jsonify({
                "error": "path_not_allowed",
                "message": f"{len(bad)} 個檔案不在允許清單:{bad[0]}",
            }), 403

    with ResultStore() as store:
        if not file_paths and folder:
            items = store.get_failed_results(folder=folder, limit=5000)
            file_paths = [it["file_path"] for it in items]
        if not file_paths:
            return jsonify({"error": "no failures to retry"}), 400
        cleared = store.clear_failed(file_paths)
    return jsonify({
        "cleared": cleared,
        "file_paths": file_paths,
        "folder": folder,
    })


@results_bp.route("/detail", methods=["POST"])
def get_result_detail():
    """Look up a single result by file path via POST body.

    Why POST:GET /<path:file_path> doesn't survive URL-encoded absolute
    paths — encodeURIComponent turns `/Users/...` into `%2FUsers%2F...`,
    Werkzeug unquotes back to `//Users/...`, and the path converter
    fails to match the double slash. Every dogfood click on a "最近結果"
    green-light row fell through to 404 → UI's "找不到詳情" branch, even
    though the row had a complete result_json. POST body sidesteps the
    whole URL-pathing dance. (v0.13.4 fix.)"""
    data = request.get_json(silent=True) or {}
    file_path = data.get("file_path") or data.get("path") or ""
    if not isinstance(file_path, str) or not file_path:
        return jsonify({"error": "file_path required"}), 400
    with ResultStore() as store:
        result = store.get_result_with_usage(file_path)
    if result is None:
        return jsonify({"error": "Result not found"}), 404
    result["file_path"] = file_path
    return jsonify(result)


@results_bp.route("/<path:file_path>", methods=["GET"])
def get_result(file_path):
    with ResultStore() as store:
        result = store.get_result_with_usage(f"/{file_path}")
    if result is None:
        return jsonify({"error": "Result not found"}), 404
    result["file_path"] = f"/{file_path}"
    return jsonify(result)


@results_bp.route("/<path:file_path>", methods=["PUT"])
def update_result(file_path):
    data = request.get_json()
    with ResultStore() as store:
        store.update_result(f"/{file_path}", data)
    return jsonify({"status": "ok"})


@results_bp.route("/write-metadata", methods=["POST"])
def write_all_metadata():
    with ResultStore() as store:
        results = store.get_all_results()

    success = 0
    failed = 0
    for r in results:
        if write_metadata(r["file_path"], r):
            success += 1
        else:
            failed += 1

    return jsonify({"success": success, "failed": failed})
