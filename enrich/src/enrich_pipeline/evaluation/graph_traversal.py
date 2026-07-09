"""Build graph traversal questions and portable SPARQL checks."""

import re

from enrich_pipeline.models import Label, Triple


ITEMS_PER_ROW = 3
PREFIX_BLOCK = """PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""


def entity_name(entity_id: str, labels: dict[str, Label]) -> str:
    """Return a readable entity name."""
    label = labels.get(entity_id)
    return label.value if label else "unlabeled entity"


def answer_value(entity_id: str, labels: dict[str, Label]) -> str:
    """Return the human-readable answer value without Wikidata IDs when possible."""
    label = labels.get(entity_id)
    return label.value if label else entity_id


def single_quoted(value: str) -> str:
    """Return a single-quoted string with escaped control characters."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f"'{escaped}'"


def format_maps(items: list[dict[str, str]]) -> str:
    """Format question maps using single quotes for legacy consumers."""
    if not items:
        return "[]"

    formatted_items = []
    for item in items:
        lines = ["  {"]
        fields = list(item.items())
        for index, (key, value) in enumerate(fields):
            comma = "," if index < len(fields) - 1 else ""
            lines.append(f"    {single_quoted(key)}: {single_quoted(value)}{comma}")
        lines.append("  }")
        formatted_items.append("\n".join(lines))
    return "[\n" + ",\n".join(formatted_items) + "\n]"


def row_identifier(description_identifier: str, index: int) -> str:
    """Return a stable enrichment row ID such as ``Jaguar_01``."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", description_identifier).strip("_")
    return f"{cleaned or 'entity'}_{index:02d}"


def sparql_literal(label: Label) -> str:
    """Return a SPARQL string literal with a language tag."""
    return f"{single_quoted(label.value)}@{label.lang}"


def normalized_sparql_string(value: str) -> str:
    """Return a normalized string literal for label comparison in SPARQL."""
    normalized = re.sub(r"\s+", " ", value).strip().casefold()
    return single_quoted(normalized)


def predicate_name(predicate: str) -> str:
    """Return a local predicate name without a prefix."""
    return predicate.split(":", 1)[-1]


def portable_predicate_filter(variable: str, predicate: str) -> str:
    """Return a SPARQL filter that matches predicate local names."""
    normalized = re.sub(r"[^A-Za-z0-9]", "", predicate_name(predicate)).casefold()
    return (
        f"  FILTER(LCASE(REPLACE(STR({variable}), '^.*[#/]', '')) = "
        f"{single_quoted(normalized)})"
    )


def normalized_text(value: str) -> str:
    """Normalize text for ranking generated questions."""
    return re.sub(r"[^A-Za-z0-9]+", " ", value).strip().casefold()


def query_term(
    entity_id: str, role: str, index: int, labels: dict[str, Label]
) -> tuple[list[str], str]:
    """Return label lookup clauses and a generic variable for an entity."""
    label = labels.get(entity_id)
    variable = f"?{role}{index}"
    if label is None:
        return [], entity_id
    return [f"  {variable} rdfs:label {sparql_literal(label)} ."], variable


def answer_query(triples: list[Triple], labels: dict[str, Label]) -> str:
    """Build a label-based query that returns the final path answer.

    The dataset RDF defines the expected subject and answer, but generated KGs
    may use different IRIs or predicates. The query therefore matches labels and
    checks that the answer is reachable from the subject in one or two hops.
    """
    source_label = labels.get(triples[0].subject)
    final_label = labels.get(triples[-1].object)

    if source_label is None or final_label is None:
        return exact_path_query(triples, labels)

    lines = [
        "  ?subject rdfs:label ?subjectLabel .",
        (
            "  FILTER(LCASE(REPLACE(STR(?subjectLabel), '\\\\s+', ' ')) = "
            f"{normalized_sparql_string(source_label.value)})"
        ),
        "  ?answerEntity rdfs:label ?answerLabel .",
        (
            "  FILTER(LCASE(REPLACE(STR(?answerLabel), '\\\\s+', ' ')) = "
            f"{normalized_sparql_string(final_label.value)})"
        ),
        "  {",
        "    ?subject ?predicate1 ?answerEntity .",
        "  }",
        "  UNION",
        "  {",
        "    ?subject ?predicate1 ?intermediate .",
        "    ?intermediate ?predicate2 ?answerEntity .",
        "  }",
        "  BIND(STR(?answerLabel) AS ?answer)",
    ]

    body = "\n".join(lines)
    return f"{PREFIX_BLOCK}SELECT ?answer WHERE {{\n{body}\n}} LIMIT 1"


def exact_path_query(triples: list[Triple], labels: dict[str, Label]) -> str:
    """Build the previous exact path query when labels are unavailable."""
    path_lines: list[str] = []
    answer_term = ""
    for index, triple in enumerate(triples, 1):
        subject_clauses, subject_term = query_term(
            triple.subject, "subject", index, labels
        )
        object_clauses, object_term = query_term(triple.object, "object", index, labels)
        answer_term = object_term
        predicate_term = f"?predicate{index}"
        path_lines.extend(subject_clauses)
        path_lines.extend(object_clauses)
        path_lines.append(f"  {subject_term} {predicate_term} {object_term} .")
        path_lines.append(portable_predicate_filter(predicate_term, triple.predicate))

    final_label = labels.get(triples[-1].object)
    if final_label is not None:
        path_lines.append(f"  BIND(STR({sparql_literal(final_label)}) AS ?answer)")
    else:
        path_lines.append(f"  BIND({answer_term} AS ?answer)")

    body = "\n".join(path_lines)
    return f"{PREFIX_BLOCK}SELECT ?answer WHERE {{\n{body}\n}} LIMIT 1"


def path_rank(
    path_triples: list[Triple], labels: dict[str, Label], description: str
) -> tuple[int, int, int, int, str]:
    """Rank paths toward readable labels mentioned in the source description."""
    final_label = labels.get(path_triples[-1].object)
    final_text = final_label.value if final_label else path_triples[-1].object
    normalized_description = normalized_text(description)
    normalized_label = normalized_text(final_text)
    match = (
        re.search(
            rf"\b{re.escape(normalized_label)}\b",
            normalized_description,
        )
        if normalized_label
        else None
    )
    appears_rank = 0 if match else 1
    occurrence_rank = match.start() if match else len(normalized_description) + 1
    numeric_rank = 1 if normalized_label.replace(" ", "").isdigit() else 0
    return (
        appears_rank,
        occurrence_rank,
        numeric_rank,
        len(path_triples),
        final_text.casefold(),
    )


def build_graph_traversal_items(
    labels: dict[str, Label],
    root_entities: set[str],
    triples: list[Triple],
    description: str = "",
) -> list[dict[str, str]]:
    """Create graph traversal questions and SPARQL queries for each path."""
    if not triples:
        return []

    by_subject: dict[str, list[Triple]] = {}
    for triple in triples:
        by_subject.setdefault(triple.subject, []).append(triple)

    paths: list[tuple[str, list[Triple]]] = []
    for triple in triples:
        if triple.subject in root_entities:
            source = entity_name(triple.subject, labels)
            target = entity_name(triple.object, labels)
            paths.append((f"{source} --{triple.predicate}--> {target}", [triple]))

            for next_triple in by_subject.get(triple.object, []):
                final_target = entity_name(next_triple.object, labels)
                paths.append(
                    (
                        f"{source} --{triple.predicate}--> {target} "
                        f"--{next_triple.predicate}--> {final_target}",
                        [triple, next_triple],
                    )
                )

    if not paths:
        paths = [
            (
                f"{entity_name(triple.subject, labels)} --{triple.predicate}--> "
                f"{entity_name(triple.object, labels)}",
                [triple],
            )
            for triple in triples
        ]

    ranked_paths = sorted(paths, key=lambda item: path_rank(item[1], labels, description))

    items = []
    for path, path_triples in ranked_paths[:ITEMS_PER_ROW]:
        final_entity = path_triples[-1].object
        items.append(
            {
                "question": f"What answer is reached by this graph path: {path}?",
                "sparql": answer_query(path_triples, labels),
                "answer": answer_value(final_entity, labels),
            }
        )
    return items


def build_graph_traversal(
    labels: dict[str, Label], root_entities: set[str], triples: list[Triple]
) -> str:
    """Return graph traversal questions in the legacy single-cell format."""
    return format_maps(build_graph_traversal_items(labels, root_entities, triples))
