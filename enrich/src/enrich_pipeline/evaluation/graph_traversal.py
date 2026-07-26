"""Build direct-link questions and portable SPARQL checks."""

import re

from enrich_pipeline.models import (
    GraphQuestion,
    Label,
    TraversalCandidate,
    Triple,
)


ITEMS_PER_ROW = 2
PREFIX_BLOCK = """PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX schema: <https://schema.org/>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
"""


def entity_name(entity_id: str, labels: dict[str, Label]) -> str:
    """Return a readable entity name for question text."""
    label = labels.get(entity_id)
    return label.value if label else "unlabeled entity"


def answer_value(entity_id: str, labels: dict[str, Label]) -> str:
    """Return a readable answer, falling back to the prefixed ID."""
    label = labels.get(entity_id)
    return label.value if label else entity_id


def row_identifier(description_identifier: str, index: int) -> str:
    """Return a stable enrichment row ID such as ``Jaguar_01_01``."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", description_identifier).strip("_")
    return f"{cleaned or 'entity'}_{index:02d}"


def sparql_iri_from_prefixed(term: str) -> str | None:
    """Return a full SPARQL IRI for project-supported prefixed terms."""
    namespaces = {
        "wd:": "http://www.wikidata.org/entity/",
        "kg:": "https://example.org/wikidata-description/",
    }
    for prefix, namespace in namespaces.items():
        if term.startswith(prefix):
            return f"<{namespace}{term.removeprefix(prefix)}>"
    return None


def normalized_text(value: str) -> str:
    """Normalize text for ranking generated questions."""
    return re.sub(r"[^A-Za-z0-9]+", " ", value).strip().casefold()


def infer_root_entities(triples: list[Triple]) -> set[str]:
    """Return subjects that never occur as an object."""
    return {triple.subject for triple in triples} - {triple.object for triple in triples}


def traversal_candidates(
    triples: list[Triple], labels: dict[str, Label]
) -> list[TraversalCandidate]:
    """Create forward and reverse direct-link candidates with labeled sources."""
    candidates: list[TraversalCandidate] = []
    for triple in triples:
        if triple.subject in labels:
            candidates.append(
                TraversalCandidate(triple.subject, triple.object, supports_id_query=True)
            )
        if triple.object in labels:
            candidates.append(
                TraversalCandidate(triple.object, triple.subject, supports_id_query=False)
            )
    return candidates


def candidate_rank(
    candidate: TraversalCandidate,
    labels: dict[str, Label],
    description: str,
    preferred_sources: set[str],
) -> tuple[int, int, int, int, str]:
    """Rank candidates by preferred source and target mention in the text."""
    target_text = answer_value(candidate.target, labels)
    normalized_description = normalized_text(description)
    normalized_target = normalized_text(target_text)
    match = (
        re.search(rf"\b{re.escape(normalized_target)}\b", normalized_description)
        if normalized_target
        else None
    )
    return (
        0 if candidate.source in preferred_sources else 1,
        0 if match else 1,
        match.start() if match else len(normalized_description) + 1,
        1 if normalized_target.replace(" ", "").isdigit() else 0,
        target_text.casefold(),
    )


def select_candidates(
    candidates: list[TraversalCandidate],
    labels: dict[str, Label],
    description: str,
    preferred_sources: set[str],
    limit: int = ITEMS_PER_ROW,
) -> list[TraversalCandidate]:
    """Select ranked candidates with distinct source entities."""
    ranked = sorted(
        candidates,
        key=lambda candidate: candidate_rank(
            candidate, labels, description, preferred_sources
        ),
    )
    selected: list[TraversalCandidate] = []
    selected_sources: set[str] = set()
    for candidate in ranked:
        if candidate.source in selected_sources:
            continue
        selected.append(candidate)
        selected_sources.add(candidate.source)
        if len(selected) == limit:
            break
    return selected


def semantic_predicate_filter(variable: str, indent: str = "  ") -> list[str]:
    """Return a SPARQL filter that excludes naming-only predicates."""
    return [
        f"{indent}FILTER({variable} NOT IN (",
        f"{indent}  rdfs:label, skos:prefLabel, skos:altLabel, schema:name",
        f"{indent}))",
    ]


def resolved_subject_lines(source: str) -> list[str]:
    """Resolve one subject by canonical ID or structural centrality."""
    source_iri = sparql_iri_from_prefixed(source)
    canonical_rank = (
        f"IF(?subject = {source_iri}, 1, 0)"
        if source_iri is not None
        else "0"
    )
    lines = [
        "  {",
        "    SELECT ?subject",
        "           (MAX(?canonicalMatch) AS ?canonicalRank)",
        "           (SUM(?edgeWeight) AS ?subjectScore)",
        "    WHERE {",
        "      {",
        "        ?subject ?candidatePredicate ?candidateNeighbor .",
        "        BIND(2 AS ?edgeWeight)",
        "      }",
        "      UNION",
        "      {",
        "        ?candidateNeighbor ?candidatePredicate ?subject .",
        "        BIND(1 AS ?edgeWeight)",
        "      }",
        "      FILTER(isIRI(?subject) || isBlank(?subject))",
        "      FILTER(?candidateNeighbor != ?subject)",
    ]
    lines.extend(semantic_predicate_filter("?candidatePredicate", "      "))
    lines.extend([
        f"      BIND({canonical_rank} AS ?canonicalMatch)",
        "    }",
        "    GROUP BY ?subject",
        "    ORDER BY DESC(?canonicalRank) DESC(?subjectScore) STR(?subject)",
        "    LIMIT 1",
        "  }",
    ])
    return lines


def direct_edge_lines() -> list[str]:
    """Return the bidirectional one-hop pattern from the resolved subject."""
    return [
        "  {",
        "    ?subject ?predicate ?answerEntity .",
        '    BIND("outgoing" AS ?direction)',
        "  }",
        "  UNION",
        "  {",
        "    ?answerEntity ?predicate ?subject .",
        '    BIND("incoming" AS ?direction)',
        "  }",
        "  FILTER(?answerEntity != ?subject)",
    ]


def label_answer_query(source: str, labels: dict[str, Label]) -> str:
    """Return direct neighbours without requiring a matching source label."""
    if source not in labels:
        raise ValueError(f"source entity '{source}' has no label")

    lines = resolved_subject_lines(source) + direct_edge_lines()
    lines.extend(semantic_predicate_filter("?predicate"))
    lines.extend([
        "  OPTIONAL {",
        "    ?answerEntity (rdfs:label|skos:prefLabel|skos:altLabel|schema:name) ?answerLabel .",
        "  }",
        "  BIND(COALESCE(",
        "    STR(?answerLabel),",
        '    REPLACE(STR(?answerEntity), "^.*[/#]", "")',
        "  ) AS ?answer)",
    ])
    return (
        f"{PREFIX_BLOCK}SELECT DISTINCT ?answer ?subject ?direction ?predicate "
        "?answerEntity ?answerLabel WHERE {\n"
        + "\n".join(lines)
        + "\n} ORDER BY LCASE(?answer)"
    )


def predicate_answer_query(source: str, labels: dict[str, Label]) -> str:
    """Return predicates on direct edges from the resolved subject."""
    if source not in labels:
        raise ValueError(f"source entity '{source}' has no label")

    lines = resolved_subject_lines(source) + direct_edge_lines()
    lines.extend(semantic_predicate_filter("?predicate"))
    lines.append(
        '  BIND(REPLACE(STR(?predicate), "^.*[/#]", "") AS ?answer)'
    )
    return (
        f"{PREFIX_BLOCK}SELECT DISTINCT ?answer ?subject ?direction ?predicate "
        "?answerEntity WHERE {\n"
        + "\n".join(lines)
        + "\n} ORDER BY LCASE(?answer)"
    )


def graph_scoped_id_query(
    candidate: TraversalCandidate, labels: dict[str, Label]
) -> str:
    """Return an exact target ID directly linked to the resolved subject."""
    target_iri = sparql_iri_from_prefixed(candidate.target)
    if target_iri is None:
        return ""

    lines = resolved_subject_lines(candidate.source)
    lines.extend([
        f"  VALUES ?answer {{ {target_iri} }}",
        "  {",
        "    ?subject ?predicate1 ?answer .",
        "  }",
        "  UNION",
        "  {",
        "    ?answer ?predicate1 ?subject .",
        "  }",
    ])
    lines.extend(semantic_predicate_filter("?predicate1"))
    return (
        f"{PREFIX_BLOCK}SELECT DISTINCT ?answer ?subject ?predicate1 WHERE {{\n"
        + "\n".join(lines)
        + "\n} LIMIT 1"
    )


def build_graph_question(
    candidate: TraversalCandidate,
    labels: dict[str, Label],
) -> GraphQuestion:
    """Build label and optional ID queries for one selected candidate."""
    source_name = entity_name(candidate.source, labels)
    target_name = entity_name(candidate.target, labels)
    id_sparql = (
        graph_scoped_id_query(candidate, labels)
        if candidate.supports_id_query
        else ""
    )
    answer_id = candidate.target if id_sparql else ""
    return GraphQuestion(
        question=f"Which entities are directly linked to {source_name}?",
        query_type="entity",
        id_question=f"is the entity {source_name} directly linked to {target_name}?",
        sparql=label_answer_query(candidate.source, labels),
        answer_id=answer_id,
        id_sparql=id_sparql,
    )


def build_predicate_question(
    candidate: TraversalCandidate,
    labels: dict[str, Label],
) -> GraphQuestion:
    """Build the second label query, which evaluates relationship predicates."""
    source_name = entity_name(candidate.source, labels)
    return GraphQuestion(
        question=f"Which predicates directly link entities to {source_name}?",
        query_type="predicate",
        id_question="",
        sparql=predicate_answer_query(candidate.source, labels),
        answer_id="",
        id_sparql="",
    )


def build_graph_traversal_items(
    labels: dict[str, Label],
    root_entities: set[str],
    triples: list[Triple],
    description: str = "",
) -> list[GraphQuestion]:
    """Create up to ``ITEMS_PER_ROW`` direct-link questions."""
    if not triples:
        return []
    preferred_sources = root_entities or infer_root_entities(triples)
    selected = select_candidates(
        traversal_candidates(triples, labels),
        labels,
        description,
        preferred_sources,
        limit=1,
    )
    if not selected:
        return []
    candidate = selected[0]
    return [
        build_graph_question(candidate, labels),
        build_predicate_question(candidate, labels),
    ]
