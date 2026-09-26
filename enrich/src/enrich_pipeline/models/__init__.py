"""Shared data models for enrichment."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Label:
    """A parsed RDF label and its language tag."""

    value: str
    lang: str


@dataclass(frozen=True)
class Triple:
    """A simple RDF triple represented with prefixed Turtle terms."""

    subject: str
    predicate: str
    object: str


@dataclass(frozen=True)
class TraversalCandidate:
    """One direct graph connection considered for question generation."""

    source: str
    target: str
    supports_id_query: bool


@dataclass(frozen=True)
class GraphQuestion:
    """A label-based question and its optional directed ID check."""

    question: str
    query_type: str
    id_question: str
    sparql: str
    answer_id: str
    id_sparql: str

