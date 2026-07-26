#!/usr/bin/env python3
"""Command-line interface for enrichment CSV generation."""

import argparse
import sys
from pathlib import Path

from enrich_pipeline.io.enrichment_csv import enrich_csv


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Read a Wikidata description/RDF CSV and write SPARQL question rows."
    )
    parser.add_argument(
        "--input",
        default="data/wikidata_base.csv",
        help="Input CSV path (default: data/wikidata_base.csv)",
    )
    parser.add_argument(
        "--output",
        default="data/wikidata_label_sparql.csv",
        help="Output CSV path (default: data/wikidata_label_sparql.csv)",
    )
    parser.add_argument(
        "--id-output",
        default="data/wikidata_id_sparql.csv",
        help="ID SPARQL CSV path (default: data/wikidata_id_sparql.csv)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run enrichment and return a process exit code."""
    args = parse_arguments(argv)
    input_path = Path(args.input)
    output_path = Path(args.output)
    id_output_path = Path(args.id_output)

    if not input_path.exists():
        print(f"Error: input CSV '{input_path}' does not exist.", file=sys.stderr)
        return 1

    try:
        row_count = enrich_csv(input_path, output_path, id_output_path)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {row_count} graph traversal question rows to {output_path}.")
    print(f"Wrote ID-based SPARQL rows to {id_output_path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
