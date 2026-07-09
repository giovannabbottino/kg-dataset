"""Validate generated SPARQL queries against their source RDF graph."""

from rdflib import Graph


def _readable_value(value) -> str:
    """Return a comparable string for RDFLib query result values."""
    text = str(value)
    wikidata_prefix = "http://www.wikidata.org/entity/"
    if text.startswith(wikidata_prefix):
        return f"wd:{text.removeprefix(wikidata_prefix)}"
    return text


def query_returns_answer(rdf: str, sparql: str, expected_answer: str) -> bool:
    """Return whether a SPARQL query returns the expected answer value."""
    try:
        graph = Graph()
        graph.parse(data=rdf, format="turtle")
        results = graph.query(sparql)
        for row in results:
            if row and _readable_value(row[0]) == expected_answer:
                return True
        return False
    except Exception:
        return False
