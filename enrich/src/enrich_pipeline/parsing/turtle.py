"""Parse the small Turtle subset produced by the generation step."""

import re

from enrich_pipeline.models import Label, Triple


TURTLE_TERM = r"(?:wd:Q\d+|kg:[A-Za-z_][\w-]*|rdfs:Resource)"


def _unquote_label(value: str) -> Label | None:
    match = re.match(r"""rdfs:label\s+(["'])(.*)\1@([a-zA-Z-]+)$""", value)
    if not match:
        return None
    label = (
        match.group(2)
        .replace("\\'", "'")
        .replace('\\"', '"')
        .replace("\\n", "\n")
    )
    return Label(label, match.group(3))


def parse_turtle(rdf: str) -> tuple[dict[str, Label], set[str], list[Triple]]:
    """Parse the project Turtle subset into labels, root entities, and triples."""
    labels: dict[str, Label] = {}
    root_entities: set[str] = set()
    triples: list[Triple] = []
    block_lines: list[str] = []

    for raw_line in rdf.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("@prefix"):
            continue

        block_lines.append(line)
        if line.endswith("."):
            block = " ".join(block_lines)
            block_lines = []
            subject_match = re.match(rf"^({TURTLE_TERM})\s+(.+)\s+\.$", block)
            if not subject_match:
                continue

            subject = subject_match.group(1)
            statements = [
                statement.strip()
                for statement in subject_match.group(2).split(";")
            ]
            for statement in statements:
                if re.match(rf"^a\s+({TURTLE_TERM})$", statement):
                    root_entities.add(subject)
                    continue

                label = _unquote_label(statement)
                if label is not None:
                    labels[subject] = label
                    continue

                triple_match = re.match(
                    rf"^({TURTLE_TERM})\s+({TURTLE_TERM})$", statement
                )
                if triple_match:
                    triples.append(
                        Triple(subject, triple_match.group(1), triple_match.group(2))
                    )

    return labels, root_entities, triples

