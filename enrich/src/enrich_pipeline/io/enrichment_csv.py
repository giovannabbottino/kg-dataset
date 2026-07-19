"""Read generated rows and write one enrichment row per graph question."""

import csv
from pathlib import Path

from enrich_pipeline.evaluation.graph_traversal import (
    build_graph_traversal_items,
    row_identifier,
)
from enrich_pipeline.evaluation.query_validation import query_returns_answer
from enrich_pipeline.parsing.turtle import parse_turtle


ENRICH_IDENTIFIER_COLUMN = "identifier"
SOURCE_IDENTIFIER_COLUMN = "identifier"
DESCRIPTION_IDENTIFIER_COLUMN = "description_identifier"
QUESTION_COLUMN = "question"
SPARQL_COLUMN = "sparql"
ANSWER_COLUMN = "answer"
ANSWER_ID_COLUMN = "answer_id"
ID_SPARQL_COLUMN = "id_sparql"
FIELDNAMES = [
    ENRICH_IDENTIFIER_COLUMN,
    DESCRIPTION_IDENTIFIER_COLUMN,
    QUESTION_COLUMN,
    SPARQL_COLUMN,
    ANSWER_COLUMN,
    ANSWER_ID_COLUMN,
    ID_SPARQL_COLUMN,
]


def enrich_csv(input_path: Path, output_path: Path) -> int:
    """Write a compact enrichment CSV and return the number of rows written."""
    with input_path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames:
            raise ValueError(f"CSV '{input_path}' is empty or has no header.")
        if "rdf" not in reader.fieldnames:
            raise ValueError(f"CSV '{input_path}' must contain an 'rdf' column.")

        rows = []
        for row_index, row in enumerate(reader, 1):
            labels, root_entities, triples = parse_turtle(row.get("rdf") or "")
            description_identifier = (
                row.get(SOURCE_IDENTIFIER_COLUMN)
                or row.get(DESCRIPTION_IDENTIFIER_COLUMN)
                or row.get("entity")
                or f"entity_{row_index:02d}"
            )
            for question_index, item in enumerate(
                build_graph_traversal_items(
                    labels,
                    root_entities,
                    triples,
                    row.get("description") or "",
                ),
                1,
            ):
                if not query_returns_answer(
                    row.get("rdf") or "", item["sparql"], item["answer"]
                ):
                    raise ValueError(
                        "Generated SPARQL did not return the expected answer "
                        f"for {description_identifier}_{question_index:02d}."
                    )
                if item["id_sparql"] and not query_returns_answer(
                    row.get("rdf") or "", item["id_sparql"], item["answer_id"]
                ):
                    raise ValueError(
                        "Generated ID SPARQL did not return the expected answer "
                        f"for {description_identifier}_{question_index:02d}."
                    )
                rows.append(
                    {
                        ENRICH_IDENTIFIER_COLUMN: row_identifier(
                            description_identifier, question_index
                        ),
                        DESCRIPTION_IDENTIFIER_COLUMN: description_identifier,
                        QUESTION_COLUMN: item["question"],
                        SPARQL_COLUMN: item["sparql"],
                        ANSWER_COLUMN: item["answer"],
                        ANSWER_ID_COLUMN: item["answer_id"],
                        ID_SPARQL_COLUMN: item["id_sparql"],
                    }
                )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)
