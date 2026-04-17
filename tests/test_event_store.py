"""tests/test_event_store.py"""

from modules.event_store import EventStore


def test_add_and_read_recent_events(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))

    with EventStore() as store:
        store.add_event(
            "watch_started",
            folder="/photos",
            file_path="/photos/a.jpg",
            details={"foo": "bar"},
        )

    with EventStore() as store:
        events = store.get_recent(limit=10)

    assert len(events) == 1
    assert events[0]["event_type"] == "watch_started"
    assert events[0]["folder"] == "/photos"
    assert events[0]["file_path"] == "/photos/a.jpg"
    assert events[0]["details"]["foo"] == "bar"
