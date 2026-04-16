"""api/results.py — Query and edit analysis results"""

from flask import Blueprint, request, jsonify

from modules.result_store import ResultStore

results_bp = Blueprint("results", __name__, url_prefix="/api/results")


@results_bp.route("", methods=["GET"])
def get_results():
    store = ResultStore()
    results = store.get_all_results()
    summary = store.get_summary()
    store.close()
    return jsonify({"results": results, "summary": summary})


@results_bp.route("/<path:file_path>", methods=["PUT"])
def update_result(file_path):
    data = request.get_json()
    store = ResultStore()
    store.update_result(f"/{file_path}", data)
    store.close()
    return jsonify({"status": "ok"})


@results_bp.route("/write-metadata", methods=["POST"])
def write_all_metadata():
    from modules.metadata_writer import write_metadata

    store = ResultStore()
    results = store.get_all_results()
    store.close()

    success = 0
    failed = 0
    for r in results:
        if write_metadata(r["file_path"], r):
            success += 1
        else:
            failed += 1

    return jsonify({"success": success, "failed": failed})
