"""Happy Vision — CLI entry point"""

import click


@click.command()
@click.argument("folder", type=click.Path(exists=True))
@click.option("--model", default="lite", type=click.Choice(["lite", "flash"]))
@click.option("--concurrency", default=5, type=int)
@click.option("--output", default=".", type=click.Path())
@click.option("--format", "fmt", default="csv", type=click.Choice(["csv", "json", "csv,json"]))
@click.option("--write-metadata", is_flag=True, default=False)
@click.option("--skip-existing", is_flag=True, default=False)
def main(folder, model, concurrency, output, fmt, write_metadata, skip_existing):
    """Analyze photos in FOLDER with Gemini AI."""
    click.echo(f"Happy Vision — analyzing {folder}")
    click.echo(f"Model: {model}, Concurrency: {concurrency}")


if __name__ == "__main__":
    main()
