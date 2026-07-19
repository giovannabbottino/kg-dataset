"""Validate generated SPARQL queries against their source RDF graph."""

import re

from rdflib import Graph


def _readable_value(value) -> str:
    """Return a comparable string for RDFLib query result values."""
    text = str(value)
    wikidata_prefix = "http://www.wikidata.org/entity/"
    if text.startswith(wikidata_prefix):
        return f"wd:{text.removeprefix(wikidata_prefix)}"
    return text


def _normalized_value(value: str) -> str:
    """Return a punctuation-insensitive comparable value."""
    return re.sub(r"[\W_]+", " ", str(value or ""), flags=re.UNICODE).strip().casefold()


def _values_match(actual: str, expected: str) -> bool:
    """Return whether actual and expected match exactly or by token containment."""
    actual_normalized = _normalized_value(actual)
    expected_normalized = _normalized_value(expected)
    actual_compact = re.sub(r"[\W_]+", "", str(actual or ""), flags=re.UNICODE).casefold()
    expected_compact = re.sub(r"[\W_]+", "", str(expected or ""), flags=re.UNICODE).casefold()
    if not actual_normalized or not expected_normalized:
        return False
    if actual_normalized == expected_normalized:
        return True
    padded_actual = f" {actual_normalized} "
    padded_expected = f" {expected_normalized} "
    return (
        padded_expected in padded_actual
        or padded_actual in padded_expected
        or actual_compact == expected_compact
        or expected_compact in actual_compact
        or actual_compact in expected_compact
    )


def query_returns_answer(rdf: str, sparql: str, expected_answer: str) -> bool:
    """Return whether a SPARQL query returns the expected answer value."""
    try:
        graph = Graph()
        graph.parse(data=rdf, format="turtle")
        results = graph.query(sparql)
        for row in results:
            if row and _values_match(_readable_value(row[0]), expected_answer):
                return True
        return False
    except Exception:
        return False
