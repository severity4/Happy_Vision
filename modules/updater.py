"""modules/updater.py — GitHub Release auto-updater for Happy Vision"""

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

from modules import update_verify
from modules.config import get_config_dir

GITHUB_REPO = "severity4/Happy_Vision"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# State shared across threads
_update_state = {
    "status": "idle",       # idle | checking | available | downloading | ready | error
    "progress": 0,          # download progress 0-100
    "latest_version": None,
    "download_url": None,
    "download_filename": None,
    "sha256sums_url": None,
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

        # Find the macOS .zip (strict: must contain macos/darwin) and the SHA256SUMS asset
        download_url = None
        download_filename = None
        sha256sums_url = None
        for asset in data.get("assets", []):
            name = asset["name"]
            lower = name.lower()
            if name == "SHA256SUMS":
                sha256sums_url = asset["browser_download_url"]
            elif ("macos" in lower or "darwin" in lower) and lower.endswith(".zip"):
                download_url = asset["browser_download_url"]
                download_filename = name

        with _lock:
            if _is_newer(tag, current):
                _update_state["status"] = "available"
                _update_state["latest_version"] = tag.lstrip("v")
                _update_state["download_url"] = download_url
                _update_state["download_filename"] = download_filename
                _update_state["sha256sums_url"] = sha256sums_url
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
        filename = state.get("download_filename") or ""
        sha256sums_url = state.get("sha256sums_url")

        if not sha256sums_url or not filename:
            raise RuntimeError(
                "Release missing SHA256SUMS asset — update rejected. "
                "Please contact the developer."
            )

        # 1. Fetch SHA256SUMS (small text file)
        req_sums = Request(sha256sums_url)
        with urlopen(req_sums, timeout=30) as resp_sums:
            sha256sums_text = resp_sums.read().decode()
        expected_hash = update_verify.parse_sha256sums(sha256sums_text, filename)

        # 2. Download the zip
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

        # 3. Verify SHA256
        update_verify.verify_sha256(Path(tmp.name), expected_hash)

        # 4. Extract and apply
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


def _get_current_app() -> Path:
    """Return the .app bundle containing the running executable."""
    current_exe = Path(sys.executable)
    # sys.executable in frozen: /path/to/HappyVision.app/Contents/MacOS/HappyVision
    return current_exe.parent.parent.parent


def _apply_update(zip_path: str):
    """Extract downloaded zip into HAPPY_VISION_HOME/pending_update/.

    Does NOT touch the currently running .app — that swap happens in
    restart_app() via a trampoline script that runs after this process exits.
    """
    pending_dir = get_config_dir() / "pending_update"
    if pending_dir.exists():
        shutil.rmtree(pending_dir)
    pending_dir.mkdir(parents=True)

    update_verify.safe_extract(Path(zip_path), pending_dir)

    # Sanity check: the new .app must exist under pending/
    found = None
    for item in pending_dir.rglob("*.app"):
        found = item
        break
    if not found:
        raise FileNotFoundError("更新檔案中找不到 .app")

    if not getattr(sys, "frozen", False):
        # Dev mode — don't touch zip_path, it may be a test fixture
        return

    # In production: remove the downloaded zip now that it's extracted
    try:
        os.unlink(zip_path)
    except OSError:
        pass  # best-effort cleanup


def _build_trampoline_script(current_pid: int, current_app: Path, pending_app: Path) -> str:
    """Return a bash script body that:
    1. Waits (polling kill -0) for current_pid to exit, up to 30 seconds.
    2. Moves current_app to <current_app>.old.
    3. Moves pending_app into current_app's location.
    4. Relaunches via /usr/bin/open.
    5. Cleans up .old and the pending_update directory via EXIT trap.
    6. Self-destructs via EXIT trap.
    """
    return f"""#!/bin/bash
set -e

PID={current_pid}
CURRENT={shlex.quote(str(current_app))}
PENDING={shlex.quote(str(pending_app))}
BACKUP="${{CURRENT}}.old"
PENDING_PARENT={shlex.quote(str(pending_app.parent))}

# Cleanup runs even if later steps fail (e.g. open returns non-zero)
cleanup() {{
  rm -rf "$BACKUP"
  rm -rf "$PENDING_PARENT"
  rm -f "$0"
}}
trap cleanup EXIT

# Wait for current process to exit (poll up to 30s)
for i in $(seq 1 60); do
  if ! kill -0 "$PID" 2>/dev/null; then
    break
  fi
  sleep 0.5
done

# Swap
if [ -e "$BACKUP" ]; then
  rm -rf "$BACKUP"
fi
mv "$CURRENT" "$BACKUP"
mv "$PENDING" "$CURRENT"

# Relaunch
/usr/bin/open "$CURRENT"

# Give the new app a moment to load before cleanup (trap handles the actual rm)
sleep 2
"""


def restart_app():
    """Write a trampoline script that waits for this process to exit, swaps
    pending_update into the running .app location, and relaunches. Then exit."""
    if not getattr(sys, "frozen", False):
        return

    current_app = _get_current_app()
    if not current_app.name.endswith(".app"):
        raise RuntimeError(f"無法定位目前的 .app: {current_app}")

    pending_dir = get_config_dir() / "pending_update"
    pending_app = None
    for item in pending_dir.rglob("*.app"):
        pending_app = item
        break
    if not pending_app:
        raise FileNotFoundError("找不到已下載的更新 — 請重新檢查更新")

    script_path = get_config_dir() / "update_trampoline.sh"
    script_path.write_text(_build_trampoline_script(
        current_pid=os.getpid(),
        current_app=current_app,
        pending_app=pending_app,
    ))
    script_path.chmod(0o755)

    # Start trampoline detached (new session), then exit ourselves so the
    # trampoline can proceed with the swap. Redirect its stdout/stderr to a
    # log file under the config dir so post-mortem diagnosis is possible.
    log_path = get_config_dir() / "update_trampoline.log"
    log_file = open(log_path, "w")
    subprocess.Popen(
        ["/bin/bash", str(script_path)],
        stdout=log_file,
        stderr=log_file,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    sys.exit(0)
