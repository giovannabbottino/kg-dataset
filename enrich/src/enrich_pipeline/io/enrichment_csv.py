"""Transform generated RDF rows into validated SPARQL CSV rows."""

import csv
import json
from pathlib import Path

from rdflib import Graph

from enrich_pipeline.evaluation.graph_traversal import (
    build_graph_traversal_items,
    row_identifier,
)
from enrich_pipeline.evaluation.query_validation import (
    parse_rdf_graph,
    query_answer_values,
    query_returns_answer,
)
from enrich_pipeline.models import GraphQuestion
from enrich_pipeline.parsing.turtle import parse_turtle


ENRICH_IDENTIFIER_COLUMN = "identifier"
SOURCE_IDENTIFIER_COLUMN = "identifier"
DESCRIPTION_IDENTIFIER_COLUMN = "description_identifier"
QUESTION_COLUMN = "question"
QUERY_TYPE_COLUMN = "query_type"
SPARQL_COLUMN = "sparql"
ANSWER_COLUMN = "answer"
ANSWER_ID_COLUMN = "answer_id"
ID_SPARQL_COLUMN = "id_sparql"
FIELDNAMES = [
    ENRICH_IDENTIFIER_COLUMN,
    DESCRIPTION_IDENTIFIER_COLUMN,
    QUESTION_COLUMN,
    QUERY_TYPE_COLUMN,
    SPARQL_COLUMN,
    ANSWER_COLUMN,
]
ID_FIELDNAMES = [
    ENRICH_IDENTIFIER_COLUMN,
    DESCRIPTION_IDENTIFIER_COLUMN,
    QUESTION_COLUMN,
    ANSWER_ID_COLUMN,
    ID_SPARQL_COLUMN,
]

CsvRow = dict[str, str]


def default_id_output_path(output_path: Path) -> Path:
    """Return the companion path for ID-based SPARQL rows."""
    return output_path.with_name(f"{output_path.stem}_id_sparql{output_path.suffix}")


def read_source_rows(input_path: Path) -> list[CsvRow]:
    """Read and validate source CSV rows."""
    with input_path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames:
            raise ValueError(f"CSV '{input_path}' is empty or has no header.")
        if "rdf" not in reader.fieldnames:
            raise ValueError(f"CSV '{input_path}' must contain an 'rdf' column.")
        return list(reader)


def source_identifier(row: CsvRow, row_index: int) -> str:
    """Return the best available source identifier for a CSV row."""
    return (
        row.get(SOURCE_IDENTIFIER_COLUMN)
        or row.get(DESCRIPTION_IDENTIFIER_COLUMN)
        or row.get("entity")
        or f"entity_{row_index:02d}"
    )


def parse_source_graph(rdf: str, identifier: str) -> Graph:
    """Parse RDFLib input and add source context to parse failures."""
    try:
        return parse_rdf_graph(rdf)
    except Exception as exc:
        raise ValueError(f"Invalid Turtle RDF for '{identifier}'.") from exc


def encode_answers(answers: list[str]) -> str:
    """Encode answers in a deterministic, case-insensitive display order."""
    ordered = sorted(answers, key=lambda value: (value.casefold(), value))
    return json.dumps(ordered, ensure_ascii=False)


def validated_label_answer(
    graph: Graph, question: GraphQuestion, identifier: str
) -> str:
    """Execute the label query and encode its non-empty result as JSON."""
    try:
        answers = query_answer_values(graph, question.sparql)
    except Exception as exc:
        raise ValueError(
            f"Generated label SPARQL failed for '{identifier}'."
        ) from exc
    if not answers:
        raise ValueError(
            f"Generated label SPARQL returned no answer for '{identifier}'."
        )
    return encode_answers(answers)


def validate_id_query(graph: Graph, question: GraphQuestion, identifier: str) -> None:
    """Ensure an optional directed ID query returns its expected Q-ID."""
    if question.id_sparql and not query_returns_answer(
        graph, question.id_sparql, question.answer_id
    ):
        raise ValueError(
            f"Generated ID SPARQL did not return the expected answer for '{identifier}'."
        )


def label_output_row(
    identifier: str,
    description_identifier: str,
    question: GraphQuestion,
    answer: str,
) -> CsvRow:
    """Build one label-based output row."""
    return {
        ENRICH_IDENTIFIER_COLUMN: identifier,
        DESCRIPTION_IDENTIFIER_COLUMN: description_identifier,
        QUESTION_COLUMN: question.question,
        QUERY_TYPE_COLUMN: question.query_type,
        SPARQL_COLUMN: question.sparql,
        ANSWER_COLUMN: answer,
    }


def id_output_row(
    identifier: str, description_identifier: str, question: GraphQuestion
) -> CsvRow:
    """Build one directed ID output row."""
    return {
        ENRICH_IDENTIFIER_COLUMN: identifier,
        DESCRIPTION_IDENTIFIER_COLUMN: description_identifier,
        QUESTION_COLUMN: question.id_question,
        ANSWER_ID_COLUMN: question.answer_id,
        ID_SPARQL_COLUMN: question.id_sparql,
    }


def enrich_source_row(row: CsvRow, row_index: int) -> tuple[list[CsvRow], list[CsvRow]]:
    """Create validated label and ID rows for one source CSV row."""
    description_identifier = source_identifier(row, row_index)
    rdf = row.get("rdf") or ""
    labels, root_entities, triples = parse_turtle(rdf)
    graph = parse_source_graph(rdf, description_identifier)
    questions = build_graph_traversal_items(
        labels,
        root_entities,
        triples,
        row.get("description") or "",
    )

    label_rows: list[CsvRow] = []
    id_rows: list[CsvRow] = []
    for question_index, question in enumerate(questions, 1):
        identifier = row_identifier(description_identifier, question_index)
        answer = validated_label_answer(graph, question, identifier)
        validate_id_query(graph, question, identifier)
        label_rows.append(
            label_output_row(identifier, description_identifier, question, answer)
        )
        if question.id_sparql:
            id_rows.append(id_output_row(identifier, description_identifier, question))
    return label_rows, id_rows


def enrich_rows(source_rows: list[CsvRow]) -> tuple[list[CsvRow], list[CsvRow]]:
    """Enrich all source rows while preserving their input order."""
    label_rows: list[CsvRow] = []
    id_rows: list[CsvRow] = []
    for row_index, row in enumerate(source_rows, 1):
        row_label_rows, row_id_rows = enrich_source_row(row, row_index)
        label_rows.extend(row_label_rows)
        id_rows.extend(row_id_rows)
    return label_rows, id_rows


def write_rows(path: Path, fieldnames: list[str], rows: list[CsvRow]) -> None:
    """Write a complete CSV with a stable header."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def enrich_csv(
    input_path: Path,
    output_path: Path,
    id_output_path: Path | None = None,
) -> int:
    """Read source rows and write validated label and ID query CSVs."""
    id_output_path = id_output_path or default_id_output_path(output_path)
    label_rows, id_rows = enrich_rows(read_source_rows(input_path))
    write_rows(output_path, FIELDNAMES, label_rows)
    write_rows(id_output_path, ID_FIELDNAMES, id_rows)
    return len(label_rows)
