#!/usr/bin/env python3
"""Fetch a Wikidata entity, save its description, and build a small RDF graph.

Usage:
    python generate/src/main.py Mango
    python generate/src/main.py car automobile
    python generate/src/main.py Mango --csv descriptions.csv
"""

import argparse
import re
import sys

from generate_pipeline.extraction.description_entities import (
    extract_entities_and_relations,
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
from generate_pipeline.clients.wikidata_client import (
    fetch_entity,
    fetch_labels,
    find_entity_ids_by_name,
)
from generate_pipeline.clients.wikipedia_client import fetch_wikipedia_phrases


LANGUAGE = "en"


def clean_wikipedia_text(text: str) -> str:
    """Remove quoted and parenthesized Wikipedia text."""
    text = re.sub(r'"[^"]*"', "", text)
    while re.search(r"\([^()]*\)", text):
        text = re.sub(r"\([^()]*\)", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


def clean_wikipedia_phrases(phrases: list[str]) -> list[str]:
    """Clean fetched Wikipedia phrases and drop empty results."""
    return [cleaned for phrase in phrases if (cleaned := clean_wikipedia_text(phrase))]


def sentence_text(text: str) -> str:
    """Return text as a sentence with one terminal punctuation mark."""
    text = text.strip()
    if not text:
        return ""
    return text if text.endswith((".", "!", "?")) else f"{text}."


def build_wikipedia_description(entity_phrases: list[str]) -> str:
    """Build a description from Wikipedia phrases only."""
    sentences = []
    seen_sentences = set()
    for phrase in entity_phrases:
        sentence = sentence_text(phrase)
        sentence_key = sentence.casefold()
        if sentence and sentence_key not in seen_sentences:
            sentences.append(sentence)
            seen_sentences.add(sentence_key)
    return " ".join(sentences)


def wikipedia_title(entity: dict, lang: str) -> str:
    """Return the Wikipedia title for an entity in the requested language."""
    sitelink = entity.get("sitelinks", {}).get(f"{lang}wiki", {})
    return sitelink.get("title", "")


def entity_identifier(names: list[str]) -> str:
    """Return a display identifier, joining two requested names with ``-``."""
    normalized = []
    for name in names:
        stripped = name.strip()
        normalized.append(
            stripped[:1].upper() + stripped[1:] if stripped else stripped
        )
    return "-".join(normalized)


def find_candidate_ids(names: list[str], lang: str) -> list[str]:
    """Resolve candidates for one ambiguous name or the first match of two names."""
    if len(names) == 1:
        return find_entity_ids_by_name(names[0], lang, limit=10)

    entity_ids = []
    for name in names:
        matches = find_entity_ids_by_name(name, lang, limit=1)
        if not matches:
            raise RuntimeError(f"no entity found for '{name}'")
        entity_ids.append(matches[0])
    if entity_ids[0] == entity_ids[1]:
        raise RuntimeError("the two names resolved to the same Wikidata entity")
    return entity_ids


def parse_arguments() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description="Fetch a Wikidata entity and append its description and RDF graph."
    )
    parser.add_argument(
        "names",
        nargs="+",
        help="One ambiguous entity name, or two names whose first matches are used",
    )
    parser.add_argument(
        "--csv",
        default="data/wikidata_description_rdf.csv",
        help="CSV file to append to (default: data/wikidata_description_rdf.csv)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    if len(args.names) not in {1, 2}:
        print("Error: provide one or two entity names", file=sys.stderr)
        return 2
    names = [name.strip() for name in args.names]
    if any(not name for name in names):
        print("Error: entity names cannot be empty", file=sys.stderr)
        return 2

    identifier = entity_identifier(names)
    try:
        if csv_has_identifier(args.csv, identifier):
            print(
                f"Skipped {identifier}: identifier already exists in {args.csv}."
            )
            return 0
    except OSError as exc:
        print(f"Error reading output CSV: {exc}", file=sys.stderr)
        return 1

    try:
        entity_ids = find_candidate_ids(names, LANGUAGE)
        if not entity_ids:
            print(f"Error: no entity found for '{names[0]}'.", file=sys.stderr)
            return 1

        entity_phrases = []
        seen_phrase_keys = set()
        selected_entity_count = 0
        rdf_graphs = []
        text_triples = []
        extracted_entity_count = 0
        for entity_id in entity_ids:
            entity = fetch_entity(entity_id, LANGUAGE)
            phrases = fetch_wikipedia_phrases(
                wikipedia_title(entity, LANGUAGE), LANGUAGE, limit=2
            )
            phrases = clean_wikipedia_phrases(phrases)
            selected_phrases = []
            for phrase in phrases:
                phrase_key = sentence_text(phrase).casefold()
                if phrase_key in seen_phrase_keys:
                    continue
                selected_phrases.append(phrase)
                if len(selected_phrases) == 2:
                    break
            if len(selected_phrases) != 2:
                continue

            seen_phrase_keys.update(
                sentence_text(phrase).casefold() for phrase in selected_phrases
            )
            entity_phrases.extend(selected_phrases)
            relation_text = " ".join(selected_phrases)
            related_ids, relations = extract_entities_and_relations(
                relation_text, LANGUAGE, entity_id
            )
            relations = dedupe_relations(relations)
            labels = fetch_labels(related_ids, LANGUAGE)
            entity_label = entity.get("labels", {}).get(LANGUAGE, {}).get("value", "")
            label_by_id = {**labels}
            if entity_label:
                label_by_id[entity_id] = entity_label
            relations = prune_redundant_relations(label_by_id, relations)
            related_ids = {object_id for _subject_id, _predicate, object_id in relations}
            # Materialize the readable triples before RDF serialization.  The
            # RDF is intentionally limited to relationships extracted from the
            # Wikipedia text; Wikidata P31/type triples are not added.
            text_triples.extend(build_text_triples(label_by_id, relations))
            rdf_graphs.append(
                build_rdf(
                    entity,
                    LANGUAGE,
                    labels,
                    related_ids,
                    relations,
                )
            )
            extracted_entity_count += len(related_ids)
            selected_entity_count += 1
            if selected_entity_count == 2:
                break

        if selected_entity_count != 2:
            print(
                f"Error: '{identifier}' must resolve to two different entities with 2 Wikipedia phrases each.",
                file=sys.stderr,
            )
            return 1

        sentence_description = build_wikipedia_description(entity_phrases)
        rdf_graph = combine_rdf_graphs(rdf_graphs)
        append_csv(
            args.csv,
            identifier,
            sentence_description,
            rdf_graph,
            text_triples,
        )
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"Error writing output files: {exc}", file=sys.stderr)
        return 1

    print(
        f"Appended 2 matches for {identifier} ({LANGUAGE}) to {args.csv} "
        f"with 4 Wikipedia phrases and {extracted_entity_count} extracted entities."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
