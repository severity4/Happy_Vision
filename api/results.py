"""api/results.py — Query and edit analysis results"""

from flask import Blueprint, request, jsonify

from modules.metadata_writer import write_metadata
from modules.result_store import ResultStore

results_bp = Blueprint("results", __name__, url_prefix="/api/results")


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
    limit = max(1, min(5000, int(request.args.get("limit", 1000))))
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
