"""tests/test_phash_prefix.py — v0.12.0 prefix-bucket dedup for 150k-row scale."""
from __future__ import annotations

import pytest

from modules.phash import prefix16, prefix_neighbours
from modules.result_store import ResultStore


@pytest.fixture
def store(tmp_path):
    s = ResultStore(tmp_path / "r.db")
    yield s
    s.close()


# ---------------- prefix16 ----------------

def test_prefix16_first_4_hex_chars():
    assert prefix16("abcd1234ffffffff") == 0xABCD
    assert prefix16("0000000000000000") == 0x0000
    assert prefix16("ffff000000000000") == 0xFFFF


def test_prefix16_handles_bad_input():
    assert prefix16("") is None
    assert prefix16(None) is None
    assert prefix16("abc") is None  # too short
    assert prefix16("gggg1234") is None  # not hex


# ---------------- prefix_neighbours ----------------

def test_prefix_neighbours_includes_target_plus_16_flips():
    n = prefix_neighbours(0xABCD, max_flips=1)
    assert len(n) == 17  # original + 16 single-bit flips
    assert 0xABCD in n
    # Each flip XORs a single bit
    assert (0xABCD ^ 0x0001) in n
    assert (0xABCD ^ 0x8000) in n


def test_prefix_neighbours_empty_when_prefix_none():
    assert prefix_neighbours(None) == []


# ---------------- find_similar with bucket index ----------------

def test_find_similar_hits_via_bucket_at_large_scale(store):
    """Save 100 rows with varied prefixes + 1 target-similar row in a
    different prefix bucket. find_similar must still locate the similar
    row via the prefix-neighbour probe (single bit flip in the first 16
    bits)."""
    # Burst twin: exact prefix match.
    store.save_result(
        "/tmp/master.jpg", {"title": "m", "keywords": []},
        phash="abcd1234567890ab",
    )
    # Noise: 200 rows with random-ish other prefixes.
    for i in range(200):
        prefix_hex = f"{(i * 37) % 0xFFFF:04x}"  # spreads prefixes around
        store.save_result(
            f"/tmp/noise_{i}.jpg", {"title": "n", "keywords": []},
            phash=prefix_hex + "000000000000",
        )

    # Target with SAME prefix as master, different tail (`b` → `0` = 3 bits).
    match = store.find_similar("abcd1234567890a0", threshold=5)
    assert match is not None
    assert match["file_path"] == "/tmp/master.jpg"
    assert match["distance"] <= 5


def test_find_similar_via_single_bit_prefix_flip(store):
    """When target and master differ in 1 bit within the 16-bit prefix,
    the original prefix query misses, but prefix_neighbours catches it."""
    # Master phash starts with 0xabcd → bits: 1010 1011 1100 1101
    store.save_result(
        "/tmp/master.jpg", {"title": "m", "keywords": []},
        phash="abcd000000000000",
    )
    # Target differs in LSB of prefix → 0xabcc. One bit flip.
    match = store.find_similar("abcc000000000000", threshold=5)
    assert match is not None
    assert match["file_path"] == "/tmp/master.jpg"


def test_find_similar_falls_back_for_legacy_rows_without_prefix(store):
    """Pre-v0.12.0 rows don't have phash_prefix populated. Dedup must
    still work against them via the fallback recent-rows scan."""
    # Insert a row with phash but clear the prefix column manually
    # (simulating migration from an older DB).
    store.save_result(
        "/tmp/legacy.jpg", {"title": "l", "keywords": []},
        phash="abcd000000000000",
    )
    with store._lock:
        store.conn.execute(
            "UPDATE results SET phash_prefix = NULL WHERE file_path = ?",
            ("/tmp/legacy.jpg",),
        )
        store.conn.commit()

    match = store.find_similar("abcd000000000000", threshold=5)
    assert match is not None
    assert match["file_path"] == "/tmp/legacy.jpg"


def test_find_similar_respects_threshold(store):
    """A match in the same prefix bucket but with Hamming > threshold
    must not be returned."""
    store.save_result(
        "/tmp/master.jpg", {"title": "m", "keywords": []},
        phash="abcd000000000000",
    )
    # Differs in a lot of bits (full flip on second half) → Hamming 32.
    match = store.find_similar("abcdffffffffffff", threshold=5)
    assert match is None


def test_save_result_populates_phash_prefix(store):
    store.save_result(
        "/tmp/x.jpg", {"title": "x", "keywords": []},
        phash="abcd1234567890ab",
    )
    row = store.conn.execute(
        "SELECT phash_prefix FROM results WHERE file_path = ?", ("/tmp/x.jpg",),
    ).fetchone()
    assert row["phash_prefix"] == 0xABCD
