"""modules/update_verify.py — Integrity checks for update packages.

Defense against zip slip (entry paths escaping the extract directory)
and oversized payloads.
"""

import hashlib
import stat
import zipfile
from pathlib import Path

MAX_ZIP_SIZE = 300 * 1024 * 1024  # 300 MB


def verify_size(size_bytes: int) -> None:
    """Raise ValueError if size exceeds the limit."""
    if size_bytes > MAX_ZIP_SIZE:
        raise ValueError(
            f"Update exceeds size limit ({size_bytes} > {MAX_ZIP_SIZE} bytes)"
        )


def _is_symlink_entry(info: zipfile.ZipInfo) -> bool:
    """Detect a symlink zip entry via the unix mode in external_attr."""
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(unix_mode)


def safe_extract(zip_path: Path, dest: Path) -> None:
    """Extract zip_path into dest, rejecting entries that could escape dest.

    Guards against:
    - Absolute paths (leading / or \\)
    - Traversal via .. in either / or \\-separated segments
    - Null bytes in entry names
    - Symlink entries (could resolve outside dest after extraction)
    """
    dest_resolved = Path(dest).resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = info.filename
            if not name:
                raise ValueError("Zip entry with empty name")
            if "\x00" in name:
                raise ValueError(f"Zip entry with null byte: {name!r}")
            if name.startswith(("/", "\\")):
                raise ValueError(f"Zip entry outside dest: {name}")
            # Normalize both separators so Windows-style paths are inspected
            normalized = name.replace("\\", "/")
            if ".." in normalized.split("/"):
                raise ValueError(f"Zip entry outside dest: {name}")
            if _is_symlink_entry(info):
                raise ValueError(f"Symlink zip entry rejected: {name}")
            target = (dest_resolved / normalized).resolve()
            try:
                target.relative_to(dest_resolved)
            except ValueError as e:
                raise ValueError(f"Zip entry outside dest: {name}") from e
        zf.extractall(dest_resolved)


def verify_sha256(file_path: Path, expected_hex: str) -> None:
    """Raise ValueError if file's SHA-256 does not match expected_hex (case-insensitive)."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if actual.lower() != expected_hex.lower():
        raise ValueError(
            f"Update checksum mismatch: expected {expected_hex[:16]}..., "
            f"got {actual[:16]}..."
        )


def parse_sha256sums(text: str, filename: str) -> str:
    """Parse a SHA256SUMS file and return the hex for the given filename.

    Format: one entry per line, '<hex>  <filename>' or '<hex> *<filename>'
    (the '*' prefix is shasum's binary-mode marker). Blank lines and lines
    starting with '#' are ignored.

    Raises ValueError if the filename isn't present.
    """
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        hex_val, name = parts
        # shasum binary mode prefixes filename with '*'
        name = name.lstrip("*").strip()
        if name == filename:
            return hex_val
    raise ValueError(f"Filename not found in SHA256SUMS: {filename}")
