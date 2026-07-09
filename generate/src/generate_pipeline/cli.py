#!/usr/bin/env python3
"""Fetch a Wikidata entity, save its description, and build a small RDF graph.

Usage:
    python generate/src/main.py Mango
    python generate/src/main.py Mango --lang pt --csv descriptions.csv
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
    dedupe_relations,
    prune_redundant_relations,
)
from generate_pipeline.clients.wikidata_client import (
    fetch_entity,
    fetch_instance_of,
    fetch_labels,
    find_entity_ids_by_name,
    instance_of_ids,
)
from generate_pipeline.clients.wikipedia_client import fetch_wikipedia_phrases


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


def entity_identifier(name: str) -> str:
    """Return a display identifier based on the requested entity name."""
    stripped = name.strip()
    return stripped[:1].upper() + stripped[1:] if stripped else stripped


def parse_arguments() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description="Fetch a Wikidata entity and append its description and RDF graph."
    )
    parser.add_argument("name", help="Wikidata entity name, e.g. Mango")
    parser.add_argument("--lang", default="en", help="Language code (default: en)")
    parser.add_argument(
        "--csv",
        default="wikidata_description_rdf.csv",
        help="CSV file to append to (default: wikidata_description_rdf.csv)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    name = args.name.strip()
    if not name:
        print("Error: name cannot be empty", file=sys.stderr)
        return 2

    try:
        entity_ids = find_entity_ids_by_name(name, args.lang, limit=10)
        if not entity_ids:
            print(f"Error: no entity found for '{name}'.", file=sys.stderr)
            return 1

        entity_phrases = []
        seen_phrase_keys = set()
        selected_entity_count = 0
        rdf_graphs = []
        text_triples = []
        extracted_entity_count = 0
        for entity_id in entity_ids:
            entity = fetch_entity(entity_id, args.lang)
            phrases = fetch_wikipedia_phrases(
                wikipedia_title(entity, args.lang), args.lang, limit=2
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
                relation_text, args.lang, entity_id
            )
            relations = dedupe_relations(relations)
            labels = fetch_labels(related_ids, args.lang)
            entity_label = entity.get("labels", {}).get(args.lang, {}).get("value", "")
            label_by_id = {**labels}
            if entity_label:
                label_by_id[entity_id] = entity_label
            relations = prune_redundant_relations(label_by_id, relations)
            related_ids = {object_id for _subject_id, _predicate, object_id in relations}
            type_ids_by_entity = fetch_instance_of(related_ids)
            type_ids_by_entity[entity_id] = instance_of_ids(entity)
            class_ids = {
                type_id
                for type_ids in type_ids_by_entity.values()
                for type_id in type_ids
            }
            class_labels = fetch_labels(class_ids, args.lang)
            text_triples.extend(build_text_triples(label_by_id, relations))
            rdf_graphs.append(
                build_rdf(
                    entity,
                    args.lang,
                    labels,
                    related_ids,
                    relations,
                    type_ids_by_entity,
                    class_labels,
                )
            )
            extracted_entity_count += len(related_ids)
            selected_entity_count += 1
            if selected_entity_count == 2:
                break

        if selected_entity_count != 2:
            print(
                f"Error: '{name}' must resolve to two different entities with 2 Wikipedia phrases each.",
                file=sys.stderr,
            )
            return 1

        sentence_description = build_wikipedia_description(entity_phrases)
        rdf_graph = combine_rdf_graphs(rdf_graphs)
        append_csv(
            args.csv,
            entity_identifier(name),
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
        f"Appended 2 matches for {name} ({args.lang}) to {args.csv} "
        f"with 4 Wikipedia phrases and {extracted_entity_count} extracted entities."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
