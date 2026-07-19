#!/usr/bin/env python3
"""Command-line interface for enrichment CSV generation."""

import argparse
import sys
from pathlib import Path

from enrich_pipeline.io.enrichment_csv import enrich_csv


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Read a Wikidata description/RDF CSV and write SPARQL question rows."
    )
    parser.add_argument(
        "--input",
        default="data/wikidata_description_rdf.csv",
        help="Input CSV path (default: data/wikidata_description_rdf.csv)",
    )
    parser.add_argument(
        "--output",
        default="data/wikidata_description_rdf_enriched.csv",
        help="Output CSV path (default: data/wikidata_description_rdf_enriched.csv)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"Error: input CSV '{input_path}' does not exist.", file=sys.stderr)
        return 1

    try:
        row_count = enrich_csv(input_path, output_path)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {row_count} graph traversal question rows to {output_path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
