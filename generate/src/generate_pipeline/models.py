"""Data models shared by the generation pipeline."""

from dataclasses import dataclass


TextTriple = tuple[str, str, str]


@dataclass(frozen=True)
class GeneratedText:
    """One description and the graph extracted from it."""

    description: str
    rdf: str
    triples: list[TextTriple]
    related_entity_count: int
