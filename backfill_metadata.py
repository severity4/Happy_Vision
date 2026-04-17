"""backfill_metadata.py — Re-write IPTC/XMP metadata for already-analyzed photos.

Use this after upgrading to v0.3.2+ to fix photos processed with an earlier
version that silently failed to write IPTC (pre-fix the writer used the
non-writable -XMP-xmp:Instructions tag; v0.3.2 switched to -XMP:UserComment).

No Gemini API calls are made — metadata is rebuilt from the cached result_json
in the local SQLite store. Idempotent: re-running is safe.

Usage:
    python3 backfill_metadata.py                 # write metadata for all completed photos in DB
    python3 backfill_metadata.py --dry-run       # preview without touching files
    python3 backfill_metadata.py --folder /path  # restrict to that folder (resolve prefix match)
    python3 backfill_metadata.py --force         # re-write even if HappyVisionProcessed marker present
"""

from pathlib import Path

import click

from modules.logger import setup_logger
from modules.metadata_writer import (
    ExiftoolBatch,
    build_exiftool_args,
    has_happy_vision_tag,
)
from modules.result_store import ResultStore

log = setup_logger("backfill_metadata")


def _load_completed(folder: str | None) -> list[dict]:
    """Load all completed results from the store, optionally filtered by folder prefix."""
    with ResultStore() as store:
        if folder:
            return store.get_results_for_folder(folder)
        return store.get_all_results()


def backfill(
    folder: str | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """Rewrite metadata for every completed photo in the DB.

    Returns a dict with counts: {written, skipped_tagged, skipped_missing,
    skipped_empty_args, failed}.
    """
    rows = _load_completed(folder)
    stats = {
        "total": len(rows),
        "written": 0,
        "skipped_tagged": 0,
        "skipped_missing": 0,
        "skipped_empty_args": 0,
        "failed": 0,
    }

    if not rows:
        return stats

    batch: ExiftoolBatch | None = None if dry_run else ExiftoolBatch()
    try:
        for row in rows:
            path = row.get("file_path", "")
            if not path or not Path(path).is_file():
                stats["skipped_missing"] += 1
                continue

            # has_happy_vision_tag spawns its own exiftool; acceptable for a
            # one-shot migration tool. In --force mode we skip the check.
            if not force and has_happy_vision_tag(path):
                stats["skipped_tagged"] += 1
                continue

            args = build_exiftool_args(row) + ["-overwrite_original"]
            if not args:
                stats["skipped_empty_args"] += 1
                continue

            if dry_run:
                stats["written"] += 1
                log.info("[dry-run] would write: %s", path)
                continue

            if batch.write(path, args):
                stats["written"] += 1
            else:
                stats["failed"] += 1
                log.warning("Write failed: %s", path)
    finally:
        if batch is not None:
            batch.close()

    return stats


@click.command()
@click.option("--dry-run", is_flag=True, default=False,
              help="Preview what would be written without touching files.")
@click.option("--folder", default=None, type=click.Path(),
              help="Restrict to photos whose path is under this folder.")
@click.option("--force", is_flag=True, default=False,
              help="Re-write even when the HappyVisionProcessed marker is already present.")
def main(dry_run, folder, force):
    """Backfill IPTC/XMP metadata for photos already in the result DB."""
    click.echo(f"Backfill mode: {'DRY-RUN' if dry_run else 'WRITE'}"
               f"{' (force)' if force else ''}"
               f"{f' folder={folder}' if folder else ''}")

    stats = backfill(folder=folder, dry_run=dry_run, force=force)

    click.echo(f"\nTotal completed photos in DB : {stats['total']}")
    click.echo(f"Written (metadata applied)   : {stats['written']}")
    click.echo(f"Skipped (already tagged)     : {stats['skipped_tagged']}")
    click.echo(f"Skipped (file missing)       : {stats['skipped_missing']}")
    click.echo(f"Skipped (no writable fields) : {stats['skipped_empty_args']}")
    click.echo(f"Failed                       : {stats['failed']}")


if __name__ == "__main__":
    main()
