"""tests/test_updater.py"""
import sys
import zipfile
from pathlib import Path

from modules import updater


def test_build_trampoline_script_substitutes_paths(tmp_path):
    """Trampoline script must contain current_app, pending, and pid."""
    script = updater._build_trampoline_script(
        current_pid=12345,
        current_app=Path("/Applications/HappyVision.app"),
        pending_app=Path("/tmp/pending/HappyVision.app"),
    )
    assert "PID=12345" in script
    assert "/Applications/HappyVision.app" in script
    assert "/tmp/pending/HappyVision.app" in script
    # 30s poll cap
    assert "seq 1 60" in script
    assert "kill -0" in script
    # Relaunch via full path
    assert "/usr/bin/open" in script
    # Trap-based cleanup + self-destruct
    assert "trap cleanup EXIT" in script
    assert 'rm -f "$0"' in script


def test_has_pending_update_true_when_pending_app_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    pending_app = tmp_path / "pending_update" / "HappyVision.app"
    pending_app.mkdir(parents=True)

    assert updater.has_pending_update() is True


def test_get_state_reports_ready_when_pending_update_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    pending_app = tmp_path / "pending_update" / "HappyVision.app"
    pending_app.mkdir(parents=True)

    with updater._lock:
        updater._update_state["status"] = "idle"
        updater._update_state["progress"] = 0

    state = updater.get_state()
    assert state["status"] == "ready"
    assert state["progress"] == 100


def test_build_trampoline_script_quotes_paths_with_spaces():
    """Paths containing spaces must be shell-quoted."""
    script = updater._build_trampoline_script(
        current_pid=1,
        current_app=Path("/Applications/Work Stuff/HappyVision.app"),
        pending_app=Path("/tmp/Pend With Spaces/HappyVision.app"),
    )
    # shlex.quote wraps in single quotes
    assert "'/Applications/Work Stuff/HappyVision.app'" in script
    assert "'/tmp/Pend With Spaces/HappyVision.app'" in script


def test_apply_update_extracts_to_pending_not_current(tmp_path, monkeypatch):
    """_apply_update must extract to pending_update/, never touch current_app."""
    # Prepare a fake zip with a fake .app
    src = tmp_path / "new.zip"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("HappyVision.app/Contents/MacOS/HappyVision", b"binary")
        z.writestr("HappyVision.app/Contents/Info.plist", b"<plist/>")

    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / "home"))

    # Fake current app — make sure _apply_update does NOT touch it
    existing = tmp_path / "existing" / "HappyVision.app"
    existing.mkdir(parents=True)
    (existing / "sentinel").write_bytes(b"old")
    monkeypatch.setattr(updater, "_get_current_app", lambda: existing)

    updater._apply_update(str(src))

    # Current app unchanged
    assert (existing / "sentinel").exists()
    assert (existing / "sentinel").read_bytes() == b"old"
    # Pending extracted into HAPPY_VISION_HOME/pending_update/
    pending = tmp_path / "home" / "pending_update" / "HappyVision.app"
    assert pending.exists()
    assert (pending / "Contents" / "Info.plist").exists()


def test_apply_update_cleans_stale_pending(tmp_path, monkeypatch):
    """Old pending_update directory must be cleared before new extract."""
    src = tmp_path / "new.zip"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("HappyVision.app/Contents/Info.plist", b"<plist/>")

    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(updater, "_get_current_app",
                        lambda: tmp_path / "existing" / "HappyVision.app")
    (tmp_path / "existing" / "HappyVision.app").mkdir(parents=True)

    # Pre-seed a stale pending with a file that should be removed
    pending_dir = tmp_path / "home" / "pending_update"
    pending_dir.mkdir(parents=True)
    (pending_dir / "stale.txt").write_bytes(b"leftover")

    updater._apply_update(str(src))

    # Stale file gone, new extract present
    assert not (pending_dir / "stale.txt").exists()
    assert (pending_dir / "HappyVision.app" / "Contents" / "Info.plist").exists()


def test_apply_update_raises_if_no_app_in_zip(tmp_path, monkeypatch):
    """If zip doesn't contain a .app bundle, raise."""
    src = tmp_path / "no_app.zip"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("README.md", b"oops")

    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(updater, "_get_current_app",
                        lambda: tmp_path / "existing" / "HappyVision.app")
    (tmp_path / "existing" / "HappyVision.app").mkdir(parents=True)

    import pytest
    with pytest.raises(FileNotFoundError):
        updater._apply_update(str(src))


def test_apply_update_dev_mode_does_not_require_current_app(tmp_path, monkeypatch):
    """In dev mode (not frozen), _apply_update still extracts but doesn't need _get_current_app."""
    src = tmp_path / "new.zip"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("HappyVision.app/Contents/Info.plist", b"<plist/>")

    monkeypatch.setattr(updater.sys, "frozen", False, raising=False)
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / "home"))

    # Should not raise; just extracts to pending
    updater._apply_update(str(src))

    pending = tmp_path / "home" / "pending_update" / "HappyVision.app"
    assert pending.exists()


def test_restart_app_noop_in_dev_mode(tmp_path, monkeypatch):
    """restart_app must return cleanly when not frozen."""
    monkeypatch.setattr(updater.sys, "frozen", False, raising=False)
    # Must not raise, must not try to read pending_update
    updater.restart_app()


def test_restart_app_raises_if_current_app_invalid(tmp_path, monkeypatch):
    """If _get_current_app returns something not ending in .app, raise."""
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater, "_get_current_app", lambda: tmp_path / "NotAnApp")
    import pytest
    with pytest.raises(RuntimeError, match="無法定位"):
        updater.restart_app()


def test_restart_app_raises_if_no_pending(tmp_path, monkeypatch):
    """If pending_update/ has no .app, raise FileNotFoundError."""
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    fake_app = tmp_path / "CurrentApp.app"
    fake_app.mkdir()
    monkeypatch.setattr(updater, "_get_current_app", lambda: fake_app)
    import pytest
    with pytest.raises(FileNotFoundError, match="找不到已下載"):
        updater.restart_app()


def test_restart_app_writes_executable_script_and_exits(tmp_path, monkeypatch):
    """Happy path: writes 0o755 trampoline, Popens it, sys.exits."""
    import subprocess
    import zipfile

    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))

    # Fake current app
    fake_app = tmp_path / "HappyVision.app"
    fake_app.mkdir()
    monkeypatch.setattr(updater, "_get_current_app", lambda: fake_app)

    # Seed a valid pending_update/HappyVision.app
    pending_app = tmp_path / "pending_update" / "HappyVision.app"
    pending_app.mkdir(parents=True)
    (pending_app / "Contents").mkdir()

    popen_calls = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            popen_calls.append({"args": args, "kwargs": kwargs})

    # Patch subprocess.Popen and sys.exit
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(updater.subprocess, "Popen", FakePopen)

    exits = []
    def fake_exit(code=0):
        exits.append(code)
        raise SystemExit(code)

    monkeypatch.setattr(updater.sys, "exit", fake_exit)

    import pytest
    with pytest.raises(SystemExit):
        updater.restart_app()

    # Verify script written and executable
    script_path = tmp_path / "update_trampoline.sh"
    assert script_path.exists()
    assert script_path.stat().st_mode & 0o777 == 0o755
    content = script_path.read_text()
    assert str(fake_app) in content
    assert str(pending_app) in content

    # Verify Popen invoked with the script and start_new_session
    assert len(popen_calls) == 1
    assert popen_calls[0]["args"] == ["/bin/bash", str(script_path)]
    assert popen_calls[0]["kwargs"].get("start_new_session") is True

    # Verify sys.exit(0) called
    assert exits == [0]

    # Log file created for trampoline output
    assert (tmp_path / "update_trampoline.log").exists()
