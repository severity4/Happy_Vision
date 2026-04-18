"""tests/test_phash.py — v0.6.0 pHash compute + similarity"""

import tempfile
from pathlib import Path

import pytest
from PIL import Image

from modules.phash import (
    are_similar,
    compute_phash,
    compute_phash_from_bytes,
    find_closest,
    hamming_distance,
)


def _make_jpg(path: Path, color=(128, 128, 128), size=(200, 200), noise_seed=None) -> Path:
    """Create a JPEG with optional per-pixel noise for distinct hashes."""
    img = Image.new("RGB", size, color=color)
    if noise_seed is not None:
        import random
        rng = random.Random(noise_seed)
        pixels = img.load()
        for x in range(0, size[0], 4):
            for y in range(0, size[1], 4):
                shift = rng.randint(-30, 30)
                c = tuple(max(0, min(255, v + shift)) for v in color)
                pixels[x, y] = c
    img.save(path, "JPEG", quality=90)
    return path


def test_compute_phash_returns_16_char_hex(tmp_path):
    p = _make_jpg(tmp_path / "a.jpg", noise_seed=1)
    h = compute_phash(p)
    assert isinstance(h, str)
    assert len(h) == 16
    int(h, 16)  # valid hex


def test_compute_phash_from_bytes_matches_compute_phash(tmp_path):
    p = _make_jpg(tmp_path / "a.jpg", noise_seed=1)
    h_path = compute_phash(p)
    h_bytes = compute_phash_from_bytes(p.read_bytes())
    assert h_path == h_bytes


def test_identical_images_have_zero_distance(tmp_path):
    a = _make_jpg(tmp_path / "a.jpg", noise_seed=42)
    b = _make_jpg(tmp_path / "b.jpg", noise_seed=42)
    assert hamming_distance(compute_phash(a), compute_phash(b)) == 0


def test_different_images_have_nonzero_distance(tmp_path):
    a = _make_jpg(tmp_path / "a.jpg", color=(200, 50, 50), noise_seed=1)
    b = _make_jpg(tmp_path / "b.jpg", color=(50, 50, 200), noise_seed=2)
    h_a, h_b = compute_phash(a), compute_phash(b)
    assert hamming_distance(h_a, h_b) > 0


def test_hamming_distance_is_symmetric(tmp_path):
    a = _make_jpg(tmp_path / "a.jpg", noise_seed=11)
    b = _make_jpg(tmp_path / "b.jpg", noise_seed=22)
    h_a, h_b = compute_phash(a), compute_phash(b)
    assert hamming_distance(h_a, h_b) == hamming_distance(h_b, h_a)


def test_hamming_distance_empty_hashes_returns_max():
    assert hamming_distance("", "abc") == 64
    assert hamming_distance("abc", "") == 64


def test_hamming_distance_invalid_hashes_returns_max():
    assert hamming_distance("not-hex", "8000000000000000") == 64


def test_are_similar_threshold_gates_distance():
    h = "8000000000000000"
    # Same hash always within any non-negative threshold
    assert are_similar(h, h, threshold=0) is True
    # Near-hash differing in 3 bits — adjust constants if test breaks with new
    # imagehash internals
    near = "8000000000000007"  # 3 bits different in last hex digit
    assert are_similar(h, near, threshold=5) is True
    assert are_similar(h, near, threshold=2) is False


def test_find_closest_picks_minimum_distance():
    target = "8000000000000000"
    candidates = [
        ("x", "8000000000000001"),  # distance 1
        ("y", "8000000000000003"),  # distance 2
        ("z", "8000000000000007"),  # distance 3
    ]
    best = find_closest(target, candidates, threshold=5)
    assert best is not None
    assert best[0] == "x"
    assert best[2] == 1


def test_find_closest_returns_none_when_all_beyond_threshold():
    target = "0000000000000000"
    candidates = [("x", "ffffffffffffffff")]  # distance 64
    assert find_closest(target, candidates, threshold=5) is None


def test_find_closest_short_circuits_on_exact_match():
    target = "8000000000000000"
    candidates = [
        ("x", "8000000000000001"),  # distance 1
        ("exact", "8000000000000000"),  # distance 0, comes after
        ("y", "8000000000000003"),
    ]
    # Should return the exact match, not the first one
    best = find_closest(target, candidates, threshold=5)
    assert best[0] == "exact"
    assert best[2] == 0


def test_find_closest_empty_candidates_returns_none():
    assert find_closest("8000000000000000", [], threshold=5) is None


def test_compute_phash_rgb_like_converts_palette_modes(tmp_path):
    # Palette-mode PNG re-saved as JPEG — pHash should still compute
    p = tmp_path / "a.jpg"
    img = Image.new("P", (100, 100))  # palette mode
    img.save(p.with_suffix(".png"))
    # Convert + save as JPEG
    Image.open(p.with_suffix(".png")).convert("RGB").save(p, "JPEG")
    h = compute_phash(p)
    assert len(h) == 16


def test_compute_phash_raises_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        compute_phash(tmp_path / "does-not-exist.jpg")
