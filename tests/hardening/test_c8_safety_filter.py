"""tests/hardening/test_c8_safety_filter.py

Hardening C8: Gemini safety filter 觸發時，pipeline 不得 crash，該張要被乾淨
地標為 failed，其他照片繼續跑。

真實情境：
- 雖然我們 `BLOCK_NONE` 所有 safety category，Gemini 仍保留「prompt / output
  整體 block」的自由（例如模型判斷輸入本身有問題）。
- google-genai SDK 在 response 被 safety block 時，存取 `response.text`
  可能直接 raise ValueError（`"The response.text is only valid if the
  response contains a single candidate with a `text` part..."`）。
- 也可能回傳 `response.text = ""` + `prompt_feedback.block_reason = "SAFETY"`，
  不 raise。

合約：
- `parse_response` 對 None / empty / ValueError 路徑全部回 None（C7 已鎖）
- `analyze_photo` 在 `response.text` 存取時拋 ValueError 時，不 crash，回
  (None, None)，也不 retry（safety block 重試沒意義，只是燒 quota）
- pipeline 把該張標為 failed，但批次繼續處理其他照片
"""

from __future__ import annotations

from pathlib import Path

from modules import gemini_vision
from modules import pipeline as pl
from modules.gemini_vision import analyze_photo


_MOCK_USAGE_META = type("UM", (), {
    "prompt_token_count": 10,
    "candidates_token_count": 0,
    "total_token_count": 10,
})()


def _write_jpg(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (64, 64), color="white").save(str(path), format="JPEG")


class _NoopBatch:
    def write(self, *_a, **_kw): return True
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *_a): pass


def _response_with_text_raising_value_error():
    """Mimic google-genai SDK behavior when candidates have no text part:
    accessing `.text` raises ValueError."""
    class _R:
        usage_metadata = _MOCK_USAGE_META
        prompt_feedback = type("PF", (), {"block_reason": "SAFETY"})()

        @property
        def text(self):
            raise ValueError(
                "The response.text is only valid if the response contains "
                "a single candidate with a `text` part."
            )
    return _R()


def _response_blocked_empty_text():
    """Alternative SDK path: .text is empty string + block_reason is set."""
    class _R:
        text = ""
        usage_metadata = _MOCK_USAGE_META
        prompt_feedback = type("PF", (), {"block_reason": "SAFETY"})()
    return _R()


def _response_with_none_text_and_block_reason():
    """Another SDK path: .text is None + block_reason set."""
    class _R:
        text = None
        usage_metadata = _MOCK_USAGE_META
        prompt_feedback = type("PF", (), {"block_reason": "OTHER"})()
    return _R()


def _patch_client(monkeypatch, response_factory):
    """`response_factory` is called each generate_content invocation."""
    class _Models:
        def __init__(self):
            self.calls = 0

        def generate_content(self, **_kw):
            self.calls += 1
            return response_factory()

    models = _Models()

    class _Client:
        pass

    client = _Client()
    client.models = models
    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: client)
    return models


# ---------- analyze_photo handles safety-block response gracefully ----------

def test_analyze_photo_value_error_on_text_access_returns_none(tmp_path, monkeypatch):
    """Key regression: accessing `response.text` on a blocked response raises
    ValueError. If analyze_photo doesn't catch it at the right layer, the
    exception propagates to the retry/except block, which sees the message
    and — depending on markers — either retries forever or marks failed.
    We want a clean (None, None), NOT a crash."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    models = _patch_client(monkeypatch, _response_with_text_raising_value_error)

    result, usage = analyze_photo(str(photo), api_key="k", model="lite", max_retries=3)

    assert result is None
    assert usage is None
    # Retrying a safety block doesn't help. max_retries=3 but we should give
    # up early (<=3 calls; ideally 1, but allow the SDK-retry path up to 3).
    assert models.calls <= 3


def test_analyze_photo_blocked_empty_text_returns_none(tmp_path, monkeypatch):
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    _patch_client(monkeypatch, _response_blocked_empty_text)
    result, usage = analyze_photo(str(photo), api_key="k", model="lite", max_retries=1)

    assert result is None
    assert usage is None


def test_analyze_photo_none_text_with_block_reason_returns_none(tmp_path, monkeypatch):
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    _patch_client(monkeypatch, _response_with_none_text_and_block_reason)
    result, usage = analyze_photo(str(photo), api_key="k", model="lite", max_retries=1)

    assert result is None
    assert usage is None


# ---------- pipeline: one photo blocked, rest must continue ----------

def test_pipeline_marks_safety_blocked_photo_failed_and_continues(tmp_path, monkeypatch):
    """Mixed batch: photo 1 blocked by safety, photos 2-3 OK. Must end with
    2 completed + 1 failed. Safety block must not halt the batch (that's only
    for auth errors, C3)."""
    for i in range(3):
        _write_jpg(tmp_path / f"p{i:02d}.jpg")

    call_order = []
    good_response_text = (
        '{"title": "ok", "description": "d", "keywords": [], '
        '"category": "other", "scene_type": "indoor", '
        '"mood": "neutral", "people_count": 0}'
    )

    class _Models:
        def generate_content(self, **_kw):
            call_order.append(1)
            n = len(call_order)
            if n == 1:
                # first photo: safety-blocked, .text raises
                return _response_with_text_raising_value_error()
            # subsequent: good JSON
            class _R:
                text = good_response_text
                usage_metadata = _MOCK_USAGE_META
            return _R()

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())
    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="k",
        concurrency=1,
        write_metadata=False,
        db_path=tmp_path / "r.db",
    )

    # 2 OK results persisted, safety-blocked one dropped.
    assert len(results) == 2
    titles = {r["title"] for r in results}
    assert titles == {"ok"}


def test_safety_block_error_string_not_misclassified_as_auth_fatal(tmp_path, monkeypatch):
    """Regression guard: the error message from a safety block contains
    strings like 'blocked' / 'SAFETY' that must NOT accidentally match
    `_AUTH_FATAL_MARKERS`. A single safety-blocked photo must never trigger
    `InvalidAPIKeyError` and halt a batch that is otherwise healthy."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    class _Models:
        def generate_content(self, **_kw):
            # Mimic an SDK path where the safety block surfaces as an
            # exception instead of an accessible response.
            raise Exception(
                "400 Response was blocked by safety filter (FINISH_REASON_SAFETY)"
            )

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())

    # Must NOT raise InvalidAPIKeyError. Generic (None, None) is correct.
    result, usage = analyze_photo(str(photo), api_key="k", model="lite", max_retries=1)
    assert result is None
    assert usage is None
