"""modules/updater.py — GitHub Release auto-updater for Happy Vision"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

from modules import update_verify

GITHUB_REPO = "severity4/Happy_Vision"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# State shared across threads
_update_state = {
    "status": "idle",       # idle | checking | available | downloading | ready | error
    "progress": 0,          # download progress 0-100
    "latest_version": None,
    "download_url": None,
    "release_notes": "",
    "error": None,
}
_lock = threading.Lock()


def get_current_version() -> str:
    """Read current version from VERSION file."""
    if getattr(sys, "frozen", False):
        version_file = Path(sys._MEIPASS) / "VERSION"
    else:
        version_file = Path(__file__).parent.parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "0.0.0"


def _parse_version(v: str) -> tuple:
    """Parse 'x.y.z' into (x, y, z) for comparison."""
    v = v.lstrip("v")
    parts = v.split(".")
    result = []
    for p in parts:
        try:
            result.append(int(p))
        except ValueError:
            result.append(0)
    return tuple(result)


def _is_newer(remote: str, local: str) -> bool:
    return _parse_version(remote) > _parse_version(local)


def get_state() -> dict:
    with _lock:
        return dict(_update_state)


def check_for_update() -> dict:
    """Check GitHub for a newer release. Returns state dict."""
    with _lock:
        _update_state["status"] = "checking"
        _update_state["error"] = None

    try:
        req = Request(GITHUB_API, headers={"Accept": "application/vnd.github.v3+json"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        tag = data.get("tag_name", "")
        current = get_current_version()

        # Find the macOS .zip or .dmg asset
        download_url = None
        for asset in data.get("assets", []):
            name = asset["name"].lower()
            if "macos" in name or "darwin" in name or name.endswith(".zip"):
                download_url = asset["browser_download_url"]
                break

        with _lock:
            if _is_newer(tag, current):
                _update_state["status"] = "available"
                _update_state["latest_version"] = tag.lstrip("v")
                _update_state["download_url"] = download_url
                _update_state["release_notes"] = data.get("body", "")
            else:
                _update_state["status"] = "idle"
                _update_state["latest_version"] = tag.lstrip("v")

        return get_state()

    except (URLError, json.JSONDecodeError, KeyError) as e:
        with _lock:
            _update_state["status"] = "error"
            _update_state["error"] = str(e)
        return get_state()


def download_and_install() -> dict:
    """Download the latest release and replace current app bundle."""
    state = get_state()
    if state["status"] != "available" or not state["download_url"]:
        return get_state()

    with _lock:
        _update_state["status"] = "downloading"
        _update_state["progress"] = 0

    try:
        url = state["download_url"]
        req = Request(url)
        with urlopen(req, timeout=300) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            if total > 0:
                update_verify.verify_size(total)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
            downloaded = 0
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                tmp.write(chunk)
                downloaded += len(chunk)
                if downloaded > update_verify.MAX_ZIP_SIZE:
                    tmp.close()
                    Path(tmp.name).unlink(missing_ok=True)
                    raise ValueError("Update exceeded size limit during download")
                if total > 0:
                    with _lock:
                        _update_state["progress"] = int(downloaded / total * 100)
            tmp.close()

        # Extract and replace app bundle
        _apply_update(tmp.name)

        with _lock:
            _update_state["status"] = "ready"
            _update_state["progress"] = 100

        return get_state()

    except Exception as e:
        with _lock:
            _update_state["status"] = "error"
            _update_state["error"] = str(e)
        return get_state()


def _apply_update(zip_path: str):
    """Extract downloaded zip and replace the current .app bundle."""
    extract_dir = Path(tempfile.mkdtemp(prefix="happyvision_update_"))

    # Safe extraction with zip slip + absolute path protection
    update_verify.safe_extract(Path(zip_path), extract_dir)

    # Find the .app inside extracted files
    app_bundle = None
    for item in extract_dir.rglob("*.app"):
        app_bundle = item
        break

    if not app_bundle:
        raise FileNotFoundError("更新檔案中找不到 .app")

    if not getattr(sys, "frozen", False):
        # Dev mode — just clean up, nothing to replace
        shutil.rmtree(extract_dir, ignore_errors=True)
        os.unlink(zip_path)
        return

    # Find current .app location
    # sys.executable in a frozen app: /path/to/HappyVision.app/Contents/MacOS/HappyVision
    current_exe = Path(sys.executable)
    current_app = current_exe.parent.parent.parent  # .app bundle root

    if not current_app.name.endswith(".app"):
        raise RuntimeError(f"無法定位目前的 .app: {current_app}")

    # Move old app to trash, move new app in
    backup = current_app.with_name(current_app.name + ".old")
    if backup.exists():
        shutil.rmtree(backup)
    current_app.rename(backup)
    shutil.move(str(app_bundle), str(current_app))

    # Cleanup
    shutil.rmtree(backup, ignore_errors=True)
    shutil.rmtree(extract_dir, ignore_errors=True)
    os.unlink(zip_path)


def restart_app():
    """Restart the application after update."""
    if getattr(sys, "frozen", False):
        current_exe = Path(sys.executable)
        current_app = current_exe.parent.parent.parent
        subprocess.Popen(["open", str(current_app)])
        sys.exit(0)
