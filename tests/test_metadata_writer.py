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
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    # 3 threads × 10 writes = 30 -execute lines
    assert fake.stdin.getvalue().count("-execute\n") == 30


def test_exiftool_batch_survives_dead_process(monkeypatch):
    """If subprocess died between calls, write() must return False, not raise."""
    from modules import metadata_writer
    import io

    class DeadProc:
        def __init__(self):
            self.stdin = self
            self.stdout = io.StringIO("")

        def write(self, _data):
            raise BrokenPipeError("exiftool died")

        def flush(self):
            pass

        def readline(self):
            return ""

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 1

    monkeypatch.setattr(metadata_writer.subprocess, "Popen", lambda *a, **kw: DeadProc())

    batch = metadata_writer.ExiftoolBatch()
    ok = batch.write("/tmp/x.jpg", ["-IPTC:Headline=X"])
    assert ok is False  # must not raise


def test_exiftool_batch_rejects_path_with_newline(monkeypatch):
    """含換行的 path 會破壞 -@ - 協定, 必須拒絕而不是送進去."""
    from modules import metadata_writer
    import io

    class FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = self
        def readline(self): return "{ready}\n"
        def wait(self, timeout=None): return 0
        def poll(self): return None

    fake = FakeProc()
    monkeypatch.setattr(metadata_writer.subprocess, "Popen", lambda *a, **kw: fake)

    batch = metadata_writer.ExiftoolBatch()
    ok = batch.write("/tmp/bad\nname.jpg", ["-IPTC:Headline=X"])

    assert ok is False
    # 絕不能把壞 path 送進 stdin
    assert "bad\nname.jpg" not in fake.stdin.getvalue()


def test_exiftool_batch_rejects_path_with_nul(monkeypatch):
    from modules import metadata_writer
    import io

    class FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = self
        def readline(self): return "{ready}\n"
        def wait(self, timeout=None): return 0
        def poll(self): return None

    fake = FakeProc()
    monkeypatch.setattr(metadata_writer.subprocess, "Popen", lambda *a, **kw: fake)

    batch = metadata_writer.ExiftoolBatch()
    ok = batch.write("/tmp/nul\x00name.jpg", ["-IPTC:Headline=X"])
    assert ok is False


def test_exiftool_batch_rejects_arg_with_newline(monkeypatch):
    """Args 本身含 \\n 也會破壞協定 (例如 caption 含換行被直接塞)."""
    from modules import metadata_writer
    import io

    class FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = self
        def readline(self): return "{ready}\n"
        def wait(self, timeout=None): return 0
        def poll(self): return None

    fake = FakeProc()
    monkeypatch.setattr(metadata_writer.subprocess, "Popen", lambda *a, **kw: fake)

    batch = metadata_writer.ExiftoolBatch()
    ok = batch.write("/tmp/ok.jpg", ["-IPTC:Caption-Abstract=line1\nline2"])
    assert ok is False


def test_exiftool_batch_does_not_false_positive_on_caption_with_error(monkeypatch):
    """Tag values containing 'error' must not cause read_json to return {}."""
    from modules import metadata_writer
    import io

    class FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout_chunks = [
                '[{"SourceFile":"/tmp/x.jpg","Caption":"error handling demo"}]\n',
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

    monkeypatch.setattr(metadata_writer.subprocess, "Popen", lambda *a, **kw: FakeProc())

    batch = metadata_writer.ExiftoolBatch()
    data = batch.read_json("/tmp/x.jpg")

    # Old heuristic "'error' not in output.lower()" would make this return {}.
    # New heuristic requires line-start "Error" which this output does not have.
    assert data.get("Caption") == "error handling demo"
