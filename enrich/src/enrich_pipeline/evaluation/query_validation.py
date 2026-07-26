"""Execute and validate generated SPARQL against source RDF graphs."""

import json
import re

from rdflib import Graph


GraphSource = Graph | str


def parse_rdf_graph(rdf: str) -> Graph:
    """Parse Turtle text into an RDFLib graph."""
    return Graph().parse(data=rdf, format="turtle")


def ensure_graph(source: GraphSource) -> Graph:
    """Return an RDFLib graph for graph or Turtle input."""
    return source if isinstance(source, Graph) else parse_rdf_graph(source)


def readable_value(value) -> str:
    """Return a comparable string for an RDFLib query value."""
    text = str(value)
    wikidata_prefix = "http://www.wikidata.org/entity/"
    if text.startswith(wikidata_prefix):
        return f"wd:{text.removeprefix(wikidata_prefix)}"
    return text


def normalized_value(value: str) -> str:
    """Return a punctuation-insensitive comparable value."""
    return re.sub(r"[\W_]+", " ", str(value or ""), flags=re.UNICODE).strip().casefold()


def compact_value(value: str) -> str:
    """Return a punctuation-free comparable value."""
    return re.sub(r"[\W_]+", "", str(value or ""), flags=re.UNICODE).casefold()


def values_match(actual: str, expected: str) -> bool:
    """Return whether values match exactly or by normalized containment."""
    actual_normalized = normalized_value(actual)
    expected_normalized = normalized_value(expected)
    if not actual_normalized or not expected_normalized:
        return False
    actual_compact = compact_value(actual)
    expected_compact = compact_value(expected)
    return (
        actual_normalized == expected_normalized
        or f" {expected_normalized} " in f" {actual_normalized} "
        or f" {actual_normalized} " in f" {expected_normalized} "
        or actual_compact == expected_compact
        or expected_compact in actual_compact
        or actual_compact in expected_compact
    )


def expected_values(expected_answer: str) -> list[str]:
    """Decode a JSON answer list or wrap one scalar expected answer."""
    try:
        decoded = json.loads(expected_answer)
    except (json.JSONDecodeError, TypeError):
        return [expected_answer]
    return decoded if isinstance(decoded, list) else [expected_answer]


def query_answer_values(source: GraphSource, sparql: str) -> list[str]:
    """Execute a query and return distinct readable first-column values."""
    graph = ensure_graph(source)
    values = {readable_value(row[0]) for row in graph.query(sparql) if row}
    return sorted(values, key=str.casefold)


def answers_include_expected(actual_answers: list[str], expected_answer: str) -> bool:
    """Return whether every expected value occurs in the actual results."""
    expected = expected_values(expected_answer)
    return bool(expected) and all(
        any(values_match(actual, value) for actual in actual_answers)
        for value in expected
    )


def query_returns_answer(
    source: GraphSource, sparql: str, expected_answer: str
) -> bool:
    """Return whether a SPARQL query returns the expected answer value."""
    try:
        return answers_include_expected(
            query_answer_values(source, sparql), expected_answer
        )
    except Exception:
        return False
