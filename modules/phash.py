"""modules/phash.py — Perceptual hash + similarity for near-duplicate photos.

Activity photos (weddings, events) tend to have bursts of 5-15 near-identical
frames. Analyzing each one is wasteful: same faces, same scene, same metadata.
A difference-hash lets us detect near-duplicates cheaply — compute an 8-byte
perceptual fingerprint from the image, and two photos are "near-duplicate"
if their hashes differ by <= threshold bits (Hamming distance).

We roll our own dhash (difference hash) instead of pulling in `imagehash`:
  - imagehash hard-depends on scipy (for phash's DCT) and PyWavelets (whash).
  - PyInstaller's scipy hook transitively bundles pyarrow, polars, sklearn,
    torch, llvmlite, onnxruntime, cv2 — roughly +800 MB on the .app.
  - dhash on its own is 20 lines of Pillow and ships just fine without scipy.

Algorithm (dhash, 64-bit):
  1. Convert image to greyscale and downsample to 9x8 (LANCZOS).
  2. For each of 8 rows, compare each pair of adjacent pixels. 1 bit if the
     left pixel is brighter than the right, 0 otherwise. 8*8 = 64 bits.
  3. Pack bits into a 16-char hex string.

Typical thresholds (64-bit dhash):
  0     — identical image content (same exposure, crop, focus)
  1-4   — barely perceptible difference (same burst, same pose)
  5-8   — same subject, small movement/zoom
  9-12  — same scene, different moment
  13+   — different photos

Default for dedup is 5. Users can tune in Settings.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image


_HASH_SIZE = 8  # 8x8 difference grid → 64 bits


# ---- Compute ----

def _dhash_from_pil(img: Image.Image) -> str:
    """Core dhash. Input: any PIL image. Output: 16-char hex string."""
    # Greyscale + resize to 9 x 8 so we can compare 8 pairs per row
    grey = img.convert("L").resize(
        (_HASH_SIZE + 1, _HASH_SIZE),
        Image.LANCZOS,
    )
    pixels = grey.load()
    bits = 0
    for row in range(_HASH_SIZE):
        for col in range(_HASH_SIZE):
            left = pixels[col, row]
            right = pixels[col + 1, row]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:016x}"


def compute_phash(photo_path: str | Path) -> str:
    """Return 16-char hex dhash of a JPEG. Raises on read/decode failure."""
    with Image.open(str(photo_path)) as img:
        return _dhash_from_pil(img)


def compute_phash_from_bytes(photo_bytes: bytes) -> str:
    """Same as compute_phash but takes raw JPEG bytes."""
    with Image.open(io.BytesIO(photo_bytes)) as img:
        return _dhash_from_pil(img)


# ---- Compare ----

def hamming_distance(hash_a: str, hash_b: str) -> int:
    """Bit-level distance between two hex pHashes. 0 = identical, 64 = max."""
    if not hash_a or not hash_b:
        return 64
    try:
        a = int(hash_a, 16)
        b = int(hash_b, 16)
    except (ValueError, TypeError):
        return 64
    # popcount of XOR = Hamming distance
    return bin(a ^ b).count("1")


def are_similar(hash_a: str, hash_b: str, threshold: int = 5) -> bool:
    """True if Hamming distance <= threshold. threshold=0 means exact match."""
    return hamming_distance(hash_a, hash_b) <= threshold


def find_closest(target: str, candidates: list[tuple[str, str]],
                 threshold: int = 5) -> tuple[str, str, int] | None:
    """Scan candidates for the closest pHash to `target` within threshold.

    `candidates` is a list of (id, phash) tuples. Returns (id, phash, distance)
    of the best match, or None if no match is within threshold.

    O(n) scan — fine for up to ~100k records. If that becomes a bottleneck we
    can bucket by hex prefix or use an ANN index, but not for v0.6.0."""
    best: tuple[str, str, int] | None = None
    for cand_id, cand_hash in candidates:
        d = hamming_distance(target, cand_hash)
        if d <= threshold and (best is None or d < best[2]):
            best = (cand_id, cand_hash, d)
            if d == 0:
                return best  # perfect match, no need to scan further
    return best
