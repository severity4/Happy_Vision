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
    assert "12345" in script
    assert "/Applications/HappyVision.app" in script
    assert "/tmp/pending/HappyVision.app" in script
    # Must wait for parent to exit before moving
    assert "kill -0" in script
    # Must relaunch via /usr/bin/open
    assert "open" in script


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
