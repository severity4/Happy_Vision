"""tests/test_metadata_writer.py"""

from modules.metadata_writer import (
    build_exiftool_args,
    write_metadata,
    read_metadata,
    has_happy_vision_tag,
)


def test_build_exiftool_args_basic():
    result = {
        "title": "Speaker on stage",
        "description": "A keynote speaker addresses the audience.",
        "keywords": ["conference", "keynote"],
        "category": "ceremony",
        "mood": "formal",
        "ocr_text": ["INOUT Creative"],
        "identified_people": ["Jensen Huang"],
    }
    args = build_exiftool_args(result)
    assert "-IPTC:Headline=Speaker on stage" in args
    assert "-IPTC:Caption-Abstract=A keynote speaker addresses the audience." in args
    assert "-IPTC:Keywords=conference" in args
    assert "-IPTC:Keywords=keynote" in args
    assert "-IPTC:Keywords=Jensen Huang" in args
    assert "-XMP:Category=ceremony" in args
    assert "-XMP:Scene=formal" in args
    assert any("INOUT Creative" in a for a in args)
    assert any("HappyVision" in a for a in args)


def test_build_exiftool_args_empty_fields():
    result = {
        "title": "",
        "description": "",
        "keywords": [],
        "category": "",
        "mood": "",
        "ocr_text": [],
        "identified_people": [],
    }
    args = build_exiftool_args(result)
    assert any("HappyVision" in a for a in args)


def test_build_exiftool_args_people_added_to_keywords():
    result = {
        "title": "CEO speech",
        "description": "CEO gives speech",
        "keywords": ["speech"],
        "category": "ceremony",
        "mood": "formal",
        "ocr_text": [],
        "identified_people": ["Jensen Huang", "Lisa Su"],
    }
    args = build_exiftool_args(result)
    keyword_args = [a for a in args if a.startswith("-IPTC:Keywords=")]
    keyword_values = [a.split("=", 1)[1] for a in keyword_args]
    assert "Jensen Huang" in keyword_values
    assert "Lisa Su" in keyword_values
    assert "speech" in keyword_values


def test_exiftool_batch_write_sends_correct_commands(monkeypatch):
    """ExiftoolBatch.write should feed args + path + -execute\\n and read until {ready}."""
    from modules import metadata_writer
    import io

    class FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout_chunks = [
                "    1 image files updated\n",
                "{ready}\n",
            ]
            self._read_idx = 0
            self.stdout = self
            self.returncode = None

        def readline(self):
            if self._read_idx < len(self.stdout_chunks):
                line = self.stdout_chunks[self._read_idx]
                self._read_idx += 1
                return line
            return ""

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def poll(self):
            return self.returncode

    fake = FakeProc()
    monkeypatch.setattr(metadata_writer.subprocess, "Popen", lambda *a, **kw: fake)

    batch = metadata_writer.ExiftoolBatch()
    ok = batch.write("/tmp/photo.jpg", ["-IPTC:Headline=Test", "-overwrite_original"])

    assert ok is True
    written = fake.stdin.getvalue()
    assert "-IPTC:Headline=Test\n" in written
    assert "-overwrite_original\n" in written
    assert "/tmp/photo.jpg\n" in written
    assert "-execute\n" in written


def test_exiftool_batch_write_detects_failure(monkeypatch):
    """Error output before {ready} should return False."""
    from modules import metadata_writer
    import io

    class FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout_chunks = [
                "Error: File not found\n",
                "    0 image files updated\n",
                "{ready}\n",
            ]
            self._read_idx = 0
            self.stdout = self

        def readline(self):
            if self._read_idx < len(self.stdout_chunks):
                line = self.stdout_chunks[self._read_idx]
                self._read_idx += 1
                return line
            return ""

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return None

    fake = FakeProc()
    monkeypatch.setattr(metadata_writer.subprocess, "Popen", lambda *a, **kw: fake)

    batch = metadata_writer.ExiftoolBatch()
    ok = batch.write("/tmp/missing.jpg", ["-IPTC:Headline=X"])
    assert ok is False


def test_exiftool_batch_close_sends_shutdown(monkeypatch):
    from modules import metadata_writer
    import io

    class FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = self
            self.waited = False

        def readline(self):
            return ""

        def wait(self, timeout=None):
            self.waited = True
            return 0

        def poll(self):
            return None if not self.waited else 0

    fake = FakeProc()
    monkeypatch.setattr(metadata_writer.subprocess, "Popen", lambda *a, **kw: fake)

    batch = metadata_writer.ExiftoolBatch()
    batch.close()

    shutdown = fake.stdin.getvalue()
    assert "-stay_open\nFalse\n" in shutdown
    assert fake.waited


def test_exiftool_batch_thread_safe(monkeypatch):
    """Two threads writing through the same batch must serialize."""
    from modules import metadata_writer
    import io
    import threading

    class FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = self

        def readline(self):
            # Every write operation consumes one "{ready}" line.
            return "{ready}\n"

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return None

    fake = FakeProc()
    monkeypatch.setattr(metadata_writer.subprocess, "Popen", lambda *a, **kw: fake)

    batch = metadata_writer.ExiftoolBatch()
    errors = []

    def worker(i):
        try:
            for j in range(10):
                batch.write(f"/tmp/p{i}_{j}.jpg", [f"-IPTC:Headline=T{i}{j}"])
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert errors == []
    # 3 threads × 10 writes = 30 -execute lines
    assert fake.stdin.getvalue().count("-execute\n") == 30
