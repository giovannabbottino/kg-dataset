#!/usr/bin/env python3
"""Command-line orchestration for Wikidata/Wikipedia graph generation."""

import argparse
import re
import sys
from pathlib import Path

from generate_pipeline.clients.wikidata_client import (
    fetch_entity,
    fetch_labels,
    find_entity_ids_by_name,
)
from generate_pipeline.clients.wikipedia_client import fetch_wikipedia_phrases
from generate_pipeline.extraction.description_entities import (
    extract_relations,
)
from generate_pipeline.io.output_writers import (
    append_csv,
    build_rdf,
    build_text_triples,
    combine_rdf_graphs,
    csv_has_identifier,
    dedupe_relations,
    prune_redundant_relations,
)
from generate_pipeline.models import GeneratedText


LANGUAGE = "en"
TEXTS_PER_INPUT = 2
PHRASES_PER_TEXT = 2
AMBIGUOUS_NAME_CANDIDATE_LIMIT = 10


def clean_wikipedia_text(text: str) -> str:
    """Remove quoted and parenthesized text and normalize whitespace."""
    text = re.sub(r'"[^"]*"', "", text)
    while re.search(r"\([^()]*\)", text):
        text = re.sub(r"\([^()]*\)", "", text)
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"\s+([,.;:!?])", r"\1", text).strip()


def clean_wikipedia_phrases(phrases: list[str]) -> list[str]:
    """Clean fetched Wikipedia phrases and discard empty values."""
    return [cleaned for phrase in phrases if (cleaned := clean_wikipedia_text(phrase))]


def sentence_text(text: str) -> str:
    """Return text with exactly one existing or added terminal mark."""
    text = text.strip()
    if not text:
        return ""
    return text if text.endswith((".", "!", "?")) else f"{text}."


def phrase_key(phrase: str) -> str:
    """Return the normalized key used to compare description phrases."""
    return sentence_text(phrase).casefold()


def select_unique_phrases(
    phrases: list[str], excluded_keys: set[str], limit: int = PHRASES_PER_TEXT
) -> list[str]:
    """Select up to ``limit`` phrases not present in ``excluded_keys``."""
    selected: list[str] = []
    selected_keys: set[str] = set()
    for phrase in phrases:
        key = phrase_key(phrase)
        if not key or key in excluded_keys or key in selected_keys:
            continue
        selected.append(phrase)
        selected_keys.add(key)
        if len(selected) == limit:
            break
    return selected


def build_wikipedia_description(phrases: list[str]) -> str:
    """Join unique Wikipedia phrases into one readable description."""
    selected = select_unique_phrases(phrases, set(), limit=len(phrases))
    return " ".join(sentence_text(phrase) for phrase in selected)


def wikipedia_title(entity: dict, lang: str) -> str:
    """Return the Wikipedia title for an entity in ``lang``."""
    return entity.get("sitelinks", {}).get(f"{lang}wiki", {}).get("title", "")


def entity_label(entity: dict, lang: str) -> str:
    """Return the entity label in ``lang`` when available."""
    return entity.get("labels", {}).get(lang, {}).get("value", "")


def normalize_names(raw_names: list[str]) -> list[str]:
    """Validate and trim the one or two input names."""
    if len(raw_names) not in {1, 2}:
        raise ValueError("provide one or two entity names")
    names = [name.strip() for name in raw_names]
    if any(not name for name in names):
        raise ValueError("entity names cannot be empty")
    return names


def entity_identifier(names: list[str]) -> str:
    """Return a display identifier, joining two requested names with ``-``."""
    return "-".join(name[:1].upper() + name[1:] for name in names)


def text_identifier(identifier: str, index: int) -> str:
    """Return the identifier for one independently stored text."""
    return f"{identifier}_{index:02d}"


def output_identifiers(identifier: str) -> list[str]:
    """Return all base-CSV identifiers produced for one input."""
    return [text_identifier(identifier, index) for index in range(1, TEXTS_PER_INPUT + 1)]


def output_already_exists(csv_path: str, identifier: str) -> bool:
    """Return whether any expected base row already exists."""
    return any(csv_has_identifier(csv_path, item) for item in output_identifiers(identifier))


def find_candidate_ids(names: list[str], lang: str) -> list[str]:
    """Resolve candidates for one ambiguous name or the first match of two names."""
    if len(names) == 1:
        return find_entity_ids_by_name(
            names[0], lang, limit=AMBIGUOUS_NAME_CANDIDATE_LIMIT
        )

    entity_ids = []
    for name in names:
        matches = find_entity_ids_by_name(name, lang, limit=1)
        if not matches:
            raise RuntimeError(f"no entity found for '{name}'")
        entity_ids.append(matches[0])
    if entity_ids[0] == entity_ids[1]:
        raise RuntimeError("the two names resolved to the same Wikidata entity")
    return entity_ids


def fetch_clean_phrases(entity: dict, lang: str) -> list[str]:
    """Fetch and clean the introductory phrases for one entity."""
    phrases = fetch_wikipedia_phrases(
        wikipedia_title(entity, lang), lang, limit=PHRASES_PER_TEXT
    )
    return clean_wikipedia_phrases(phrases)


def relation_object_ids(relations: list[tuple[str, str, str]]) -> set[str]:
    """Return the object IDs referenced by relation triples."""
    return {object_id for _subject_id, _predicate, object_id in relations}


def build_generated_text(entity: dict, phrases: list[str], lang: str) -> GeneratedText:
    """Extract relations and build the readable and RDF representations."""
    source_id = entity["id"]
    relations = extract_relations(" ".join(phrases), lang, source_id)
    relations = dedupe_relations(relations)

    labels = fetch_labels(relation_object_ids(relations), lang)
    label_by_id = dict(labels)
    if source_label := entity_label(entity, lang):
        label_by_id[source_id] = source_label

    relations = prune_redundant_relations(label_by_id, relations)
    related_ids = relation_object_ids(relations)
    triples = build_text_triples(label_by_id, relations)
    rdf = build_rdf(entity, lang, labels, related_ids, relations)
    return GeneratedText(
        description=build_wikipedia_description(phrases),
        rdf=rdf,
        triples=triples,
        related_entity_count=len(related_ids),
    )


def collect_generated_texts(
    entity_ids: list[str], lang: str, required: int = TEXTS_PER_INPUT
) -> list[GeneratedText]:
    """Collect ``required`` valid, non-overlapping entity texts."""
    generated: list[GeneratedText] = []
    seen_phrase_keys: set[str] = set()

    for entity_id in entity_ids:
        entity = fetch_entity(entity_id, lang)
        selected = select_unique_phrases(
            fetch_clean_phrases(entity, lang), seen_phrase_keys
        )
        if len(selected) != PHRASES_PER_TEXT:
            continue

        generated.append(build_generated_text(entity, selected, lang))
        seen_phrase_keys.update(phrase_key(phrase) for phrase in selected)
        if len(generated) == required:
            break
    return generated


def combine_generated_texts(texts: list[GeneratedText]) -> GeneratedText:
    """Combine generated texts into one graph-record value."""
    return GeneratedText(
        description=" ".join(text.description for text in texts),
        rdf=combine_rdf_graphs([text.rdf for text in texts]),
        triples=[triple for text in texts for triple in text.triples],
        related_entity_count=sum(text.related_entity_count for text in texts),
    )


def write_generated_texts(
    csv_path: str,
    graph_csv_path: str,
    identifier: str,
    texts: list[GeneratedText],
) -> None:
    """Append independent text rows and their optional combined graph row."""
    for index, text in enumerate(texts, 1):
        append_csv(
            csv_path,
            text_identifier(identifier, index),
            text.description,
            text.rdf,
            text.triples,
        )

    if Path(graph_csv_path).resolve() == Path(csv_path).resolve():
        return
    combined = combine_generated_texts(texts)
    append_csv(
        graph_csv_path,
        identifier,
        combined.description,
        combined.rdf,
        combined.triples,
    )


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description="Fetch Wikidata entities and append their text-derived graphs."
    )
    parser.add_argument(
        "names",
        nargs="+",
        help="One ambiguous entity name, or two names whose first matches are used",
    )
    parser.add_argument(
        "--csv",
        default="data/wikidata_base.csv",
        help="CSV file to append to (default: data/wikidata_base.csv)",
    )
    parser.add_argument(
        "--graph-csv",
        default="data/wikidata_graphs.csv",
        help="Combined graph CSV (default: data/wikidata_graphs.csv)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the generation command and return a process exit code."""
    args = parse_arguments(argv)
    try:
        names = normalize_names(args.names)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    identifier = entity_identifier(names)
    try:
        if output_already_exists(args.csv, identifier):
            print(
                f"Skipped {identifier}: one or more text identifiers already exist "
                f"in {args.csv}."
            )
            return 0
    except OSError as exc:
        print(f"Error reading output CSV: {exc}", file=sys.stderr)
        return 1

    try:
        entity_ids = find_candidate_ids(names, LANGUAGE)
        if not entity_ids:
            raise RuntimeError(f"no entity found for '{names[0]}'")
        texts = collect_generated_texts(entity_ids, LANGUAGE)
        if len(texts) != TEXTS_PER_INPUT:
            raise RuntimeError(
                f"'{identifier}' must resolve to {TEXTS_PER_INPUT} different entities "
                f"with {PHRASES_PER_TEXT} Wikipedia phrases each"
            )
        write_generated_texts(args.csv, args.graph_csv, identifier, texts)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"Error writing output files: {exc}", file=sys.stderr)
        return 1

    extracted_entity_count = sum(text.related_entity_count for text in texts)
    print(
        f"Appended {len(texts)} RDF rows for {identifier} ({LANGUAGE}) to "
        f"{args.csv}, merged them into one row in {args.graph_csv}, and "
        f"extracted {extracted_entity_count} entities."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
