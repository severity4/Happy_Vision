"""tests/test_web_ui_security.py"""
import pytest

from web_ui import app, register_allowed_root, _allowed_roots


@pytest.fixture
def client():
    app.config["TESTING"] = True
    _allowed_roots.clear()
    with app.test_client() as c:
        yield c


def test_browse_inside_home_allowed(client, tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    r = client.get(f"/api/browse?path={tmp_path}")
    assert r.status_code == 200


def test_browse_outside_home_and_allowed_roots_rejected(client, tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    (tmp_path / "home").mkdir()
    r = client.get("/api/browse?path=/etc")
    assert r.status_code == 403


def test_browse_inside_allowed_root_ok(client, tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    (tmp_path / "home").mkdir()
    photos = tmp_path / "photos"
    photos.mkdir()
    register_allowed_root(photos)
    r = client.get(f"/api/browse?path={photos}")
    assert r.status_code == 200


def test_serve_photo_outside_allowed_root_rejected(client, tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    (tmp_path / "home").mkdir()
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"\xff\xd8\xff\xd9")
    r = client.get(f"/api/photo?path={outside}")
    assert r.status_code == 403


def test_serve_photo_non_jpg_rejected(client, tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    (tmp_path / "home").mkdir()
    register_allowed_root(tmp_path)
    txt = tmp_path / "note.txt"
    txt.write_text("hello")
    r = client.get(f"/api/photo?path={txt}")
    assert r.status_code == 403


def test_serve_photo_inside_allowed_root_ok(client, tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    (tmp_path / "home").mkdir()
    register_allowed_root(tmp_path)
    photo = tmp_path / "real.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xd9")
    r = client.get(f"/api/photo?path={photo}")
    assert r.status_code == 200


def test_traversal_attempt_rejected(client, tmp_path, monkeypatch):
    """Path with .. that resolves outside allowed roots must 403."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    (tmp_path / "home").mkdir()
    photos = tmp_path / "photos"
    photos.mkdir()
    register_allowed_root(photos)
    # Real file at tmp_path/evil.jpg (OUTSIDE photos)
    (tmp_path / "evil.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    evil = photos / ".." / "evil.jpg"
    r = client.get(f"/api/photo?path={evil}")
    assert r.status_code == 403
