"""modules/update_verify.py — Integrity checks for update packages.

Defense against zip slip (entry paths escaping the extract directory)
and oversized payloads.
"""

import zipfile
from pathlib import Path

MAX_ZIP_SIZE = 300 * 1024 * 1024  # 300 MB


def verify_size(size_bytes: int) -> None:
    """Raise ValueError if size exceeds the limit."""
    if size_bytes > MAX_ZIP_SIZE:
        raise ValueError(
            f"Update exceeds size limit ({size_bytes} > {MAX_ZIP_SIZE} bytes)"
        )


def safe_extract(zip_path: Path, dest: Path) -> None:
    """Extract zip_path into dest, rejecting any entry whose resolved path
    would escape dest (zip slip) or whose name is absolute."""
    dest_resolved = Path(dest).resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = info.filename
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError(f"Zip entry outside dest: {name}")
            target = (dest_resolved / name).resolve()
            try:
                target.relative_to(dest_resolved)
            except ValueError as e:
                raise ValueError(f"Zip entry outside dest: {name}") from e
        zf.extractall(dest_resolved)
