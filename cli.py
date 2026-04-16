"""Happy Vision — CLI entry point"""

import sys
from pathlib import Path

import click
from tqdm import tqdm

from modules.config import load_config
from modules.pipeline import run_pipeline, PipelineCallbacks, scan_photos
from modules.report_generator import generate_csv, generate_json
from modules.result_store import ResultStore
from modules.logger import setup_logger

log = setup_logger("cli")


class CLICallbacks(PipelineCallbacks):
    def __init__(self, progress_bar):
        self.progress_bar = progress_bar

    def on_progress(self, done, total, file_path):
        self.progress_bar.update(1)
        self.progress_bar.set_postfix_str(Path(file_path).name)

    def on_error(self, file_path, error):
        tqdm.write(f"FAIL: {Path(file_path).name} — {error}")

    def on_complete(self, total, failed):
        pass


@click.command()
@click.argument("folder", type=click.Path(exists=True))
@click.option("--model", default="lite", type=click.Choice(["lite", "flash"]),
              help="Gemini model (lite=2.0 Flash Lite, flash=2.5 Flash)")
@click.option("--concurrency", default=5, type=int, help="Parallel API calls")
@click.option("--output", default=".", type=click.Path(), help="Report output path")
@click.option("--format", "fmt", default="csv", help="Report format: csv, json, or csv,json")
@click.option("--write-metadata", is_flag=True, default=False, help="Write results to photo IPTC/XMP")
@click.option("--skip-existing", is_flag=True, default=False, help="Skip already processed photos")
@click.option("--api-key", default=None, help="Gemini API key (overrides config)")
def main(folder, model, concurrency, output, fmt, write_metadata, skip_existing, api_key):
    """Analyze photos in FOLDER with Gemini AI."""
    config = load_config()

    key = api_key or config.get("gemini_api_key", "")
    if not key:
        click.echo("ERROR: No Gemini API key. Set it with --api-key or in ~/.happy-vision/config.json")
        sys.exit(1)

    photos = scan_photos(folder)
    if not photos:
        click.echo("No JPG photos found in folder.")
        return

    click.echo(f"Happy Vision — {len(photos)} photos in {folder}")
    click.echo(f"Model: {model}, Concurrency: {concurrency}")

    with tqdm(total=len(photos), unit="photo", desc="Analyzing") as pbar:
        callbacks = CLICallbacks(pbar)
        results = run_pipeline(
            folder=folder,
            api_key=key,
            model=model,
            concurrency=concurrency,
            skip_existing=skip_existing,
            write_metadata=write_metadata,
            callbacks=callbacks,
        )

    click.echo(f"\nDone: {len(results)} analyzed")

    if results:
        output_dir = Path(output)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Only export results for photos in this folder
        folder_paths = set(str(p) for p in Path(folder).rglob("*") if p.is_file())
        store = ResultStore()
        all_results = [r for r in store.get_all_results() if r["file_path"] in folder_paths]
        store.close()

        formats = [f.strip() for f in fmt.split(",")]
        for f in formats:
            if f == "csv":
                csv_path = output_dir / "happy_vision_report.csv"
                generate_csv(all_results, csv_path)
                click.echo(f"CSV: {csv_path}")
            elif f == "json":
                json_path = output_dir / "happy_vision_report.json"
                generate_json(all_results, json_path)
                click.echo(f"JSON: {json_path}")

    if write_metadata:
        click.echo("Metadata written to photos.")


if __name__ == "__main__":
    main()
