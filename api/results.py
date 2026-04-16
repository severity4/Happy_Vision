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


@results_bp.route("/<path:file_path>", methods=["GET"])
def get_result(file_path):
    with ResultStore() as store:
        result = store.get_result(f"/{file_path}")
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
