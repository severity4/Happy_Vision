import json
from types import SimpleNamespace

class _Resp(SimpleNamespace):
    def __init__(self, text=None, usage_metadata=None):
        super().__init__()
        self.text = text
        self.usage_metadata = SimpleNamespace(**(usage_metadata or {}))


class FakeModels:
    def __init__(self, recordings):
        self._recordings = recordings

    def generate_content(self, *args, **kwargs):
        # Return the 'default' recorded analyze response if present
        an = self._recordings.get("analyze_photo", {}).get("default")
        if not an:
            raise RuntimeError("No recorded analyze_photo response available")
        return _Resp(text=an["text"], usage_metadata=an.get("usage_metadata"))


class FakeFiles:
    def __init__(self, recordings):
        self._recordings = recordings

    def upload(self, file, config=None):
        # emulate uploaded file metadata
        obj = SimpleNamespace()
        obj.name = "files/fake-upload"
        obj.size_bytes = 1234
        return obj

    def download(self, file=None):
        # Return recorded payload or empty bytes
        payload = self._recordings.get("batch", {}).get("files/download", "")
        return payload.encode("utf-8")


class FakeBatches:
    def __init__(self, recordings):
        self._recordings = recordings

    def create(self, model=None, src=None, config=None):
        job = SimpleNamespace()
        job.name = "batches/fake"
        job.state = SimpleNamespace(name="JOB_STATE_PENDING")
        return job

    def get(self, name=None):
        info = self._recordings.get("batch", {}).get("batches/get") or {}
        return SimpleNamespace(**info)

    def cancel(self, name=None):
        return None


class Client:
    def __init__(self, api_key=None, recordings_path=None):
        # load recordings from path or default file
        if recordings_path:
            with open(recordings_path, "r", encoding="utf-8") as fh:
                self._recordings = json.load(fh)
        else:
            try:
                with open("tests/fixtures/gemini/recordings.json", "r", encoding="utf-8") as fh:
                    self._recordings = json.load(fh)
            except FileNotFoundError:
                self._recordings = {}
        self.models = FakeModels(self._recordings)
        self.files = FakeFiles(self._recordings)
        self.batches = FakeBatches(self._recordings)
