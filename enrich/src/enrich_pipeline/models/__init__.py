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

