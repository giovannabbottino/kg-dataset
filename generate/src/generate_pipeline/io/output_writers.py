"""CSV and Turtle RDF output helpers."""

import csv
import json
import re
from pathlib import Path


RDF_PREFIXES = (
    "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
    "@prefix wd: <http://www.wikidata.org/entity/> .\n"
    "@prefix kg: <https://example.org/wikidata-description/> .\n\n"
)
CSV_FIELDNAMES = ["identifier", "description", "rdf", "triples"]
REQUIRED_CSV_COLUMNS = ["description", "rdf"]
UPGRADABLE_CSV_COLUMNS = ["identifier", "triples"]


def csv_has_identifier(csv_path: str | Path, identifier: str) -> bool:
    """Return whether an identifier already exists in the output CSV."""
    path = Path(csv_path)
    if not path.exists() or path.stat().st_size == 0:
        return False

    expected = identifier.strip().casefold()
    with path.open(newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames or "identifier" not in reader.fieldnames:
            return False
        return any(
            (row.get("identifier") or "").strip().casefold() == expected
            for row in reader
        )


def triples_json(triples: list[tuple[str, str, str]]) -> str:
    """Return text-extracted triples as a JSON list for CSV storage."""
    return json.dumps(prune_redundant_triples(dedupe_triples(triples)), ensure_ascii=False)


def _normalize_triple_value(value: str) -> str:
    """Normalize text for duplicate triple comparison."""
    return re.sub(r"\s+", " ", value).strip().casefold()


def _normalize_object_value(value: str) -> str:
    """Normalize object text for semantic redundancy checks."""
    normalized = value.replace("-", " ")
    normalized = re.sub(r"[^A-Za-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def dedupe_triples(triples: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """Deduplicate triples while preserving readable values."""
    unique: dict[tuple[str, str, str], tuple[str, str, str]] = {}
    for subject, predicate, object_value in triples:
        cleaned = (
            re.sub(r"\s+", " ", subject).strip(),
            re.sub(r"\s+", " ", predicate).strip(),
            re.sub(r"\s+", " ", object_value).strip(),
        )
        if not all(cleaned):
            continue
        key = tuple(_normalize_triple_value(value) for value in cleaned)
        unique.setdefault(key, cleaned)
    return sorted(unique.values(), key=lambda triple: tuple(value.casefold() for value in triple))


def _object_is_redundant(object_value: str, object_values: list[str]) -> bool:
    """Return whether an object is less useful than another object in the group."""
    normalized = _normalize_object_value(object_value)
    if not normalized:
        return True

    other_normalized = [
        _normalize_object_value(other)
        for other in object_values
        if other != object_value
    ]

    return any(
        other
        and other != normalized
        and re.search(rf"\b{re.escape(other)}\b", normalized)
        for other in other_normalized
    )


def prune_redundant_triples(
    triples: list[tuple[str, str, str]]
) -> list[tuple[str, str, str]]:
    """Remove redundant objects within each subject-predicate group."""
    grouped: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
    for triple in triples:
        grouped.setdefault((triple[0], triple[1]), []).append(triple)

    pruned = []
    for group_triples in grouped.values():
        objects = [triple[2] for triple in group_triples]
        pruned.extend(
            triple
            for triple in group_triples
            if not _object_is_redundant(triple[2], objects)
        )
    return sorted(pruned, key=lambda triple: tuple(value.casefold() for value in triple))


def dedupe_relations(
    relations: list[tuple[str, str, str]]
) -> list[tuple[str, str, str]]:
    """Deduplicate ID-based relation triples before RDF serialization."""
    return sorted(set(relations))


def prune_redundant_relations(
    label_by_id: dict[str, str], relations: list[tuple[str, str, str]]
) -> list[tuple[str, str, str]]:
    """Remove ID-based relations whose readable objects are redundant."""
    grouped: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
    for subject_id, predicate, object_id in dedupe_relations(relations):
        subject = label_by_id.get(subject_id, subject_id)
        grouped.setdefault((subject, predicate), []).append(
            (subject_id, predicate, object_id)
        )

    pruned = []
    for group_relations in grouped.values():
        objects = [
            label_by_id.get(object_id, object_id)
            for _subject_id, _predicate, object_id in group_relations
        ]
        pruned.extend(
            relation
            for relation in group_relations
            if not _object_is_redundant(
                label_by_id.get(relation[2], relation[2]), objects
            )
        )
    return sorted(pruned)


def _read_csv_header(csv_path: Path) -> list[str]:
    """Read and normalize an existing CSV header."""
    with csv_path.open(newline="", encoding="utf-8-sig") as csv_file:
        return [
            column.strip().lstrip("\ufeff") for column in next(csv.reader(csv_file), [])
        ]


def _upgrade_csv_header(
    csv_path: Path, header: list[str], column: str
) -> list[str]:
    """Add a column to an existing CSV while preserving current rows."""
    if column in header:
        return header

    fieldnames = header + [column]
    with csv_path.open(newline="", encoding="utf-8-sig") as csv_file:
        rows = list(csv.DictReader(csv_file))

    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            row.setdefault(column, "")
            writer.writerow(row)
    return fieldnames


def _existing_csv_fieldnames(csv_path: Path) -> list[str]:
    """Validate and upgrade an existing output CSV schema."""
    fieldnames = _read_csv_header(csv_path)
    missing = [
        column for column in REQUIRED_CSV_COLUMNS if column not in fieldnames
    ]
    if missing:
        raise ValueError(
            f"CSV '{csv_path}' must have the columns: {', '.join(missing)}"
        )
    for column in UPGRADABLE_CSV_COLUMNS:
        fieldnames = _upgrade_csv_header(csv_path, fieldnames, column)
    return fieldnames


def _csv_output_row(
    fieldnames: list[str],
    identifier: str,
    description: str,
    rdf_graph: str,
    triples: list[tuple[str, str, str]],
) -> dict[str, str]:
    """Build a row while preserving any existing custom columns."""
    row = {fieldname: "" for fieldname in fieldnames}
    row.update(
        {
            "identifier": identifier,
            "description": description,
            "rdf": rdf_graph,
            "triples": triples_json(triples),
        }
    )
    return row


def append_csv(
    csv_path: str | Path,
    identifier: str,
    description: str,
    rdf_graph: str,
    triples: list[tuple[str, str, str]],
) -> None:
    """Append a description, Turtle graph, and explicit triple list to a CSV file."""
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    fieldnames = CSV_FIELDNAMES if write_header else _existing_csv_fieldnames(path)

    with path.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(
            _csv_output_row(
                fieldnames, identifier, description, rdf_graph, triples
            )
        )


def _turtle_literal(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def build_rdf(
    entity: dict,
    lang: str,
    labels: dict[str, str],
    related_ids: set[str],
    relations: list[tuple[str, str, str]],
) -> str:
    """Build Turtle RDF using only relationships extracted from the text."""
    entity_id = entity["id"]
    label = entity.get("labels", {}).get(lang, {}).get("value", "")
    statements = []
    if label:
        statements.append(f'rdfs:label "{_turtle_literal(label)}"@{lang}')
    statements.extend(
        f"kg:{relation} wd:{object_id}"
        for subject_id, relation, object_id in sorted(set(relations))
        if subject_id == entity_id
    )

    lines = [f"wd:{entity_id} " + " ;\n    ".join(statements) + " .", ""]
    for item_id in sorted(related_ids):
        item_label = labels.get(item_id)
        if item_label:
            entity_statements = [
                f'rdfs:label "{_turtle_literal(item_label)}"@{lang}',
            ]
            entity_statements.extend(
                f"kg:{relation} wd:{object_id}"
                for subject_id, relation, object_id in sorted(set(relations))
                if subject_id == item_id
            )
            lines.append(f"wd:{item_id} " + " ;\n    ".join(entity_statements) + " .")
    return RDF_PREFIXES + "\n".join(lines) + "\n"


def build_text_triples(
    label_by_id: dict[str, str], relations: list[tuple[str, str, str]]
) -> list[tuple[str, str, str]]:
    """Build readable subject-predicate-object triples extracted from text."""
    triples = []
    for subject_id, predicate, object_id in sorted(set(relations)):
        subject = label_by_id.get(subject_id, subject_id)
        object_value = label_by_id.get(object_id, object_id)
        triples.append((subject, predicate, object_value))
    return triples


def combine_rdf_graphs(rdf_graphs: list[str]) -> str:
    """Combine self-contained RDF graphs while retaining a single prefix block."""
    if not rdf_graphs:
        return RDF_PREFIXES
    return rdf_graphs[0] + "".join(
        rdf_graph.removeprefix(RDF_PREFIXES) for rdf_graph in rdf_graphs[1:]
    )
