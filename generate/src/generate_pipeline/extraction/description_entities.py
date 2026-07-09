"""Extract Wikidata entities and simple relationships from description text.

Libraries used here:

- ``re`` from the Python standard library tokenizes text and locates phrase spans.
- ``nltk.pos_tag`` assigns Penn Treebank part-of-speech tags, which this module
  uses to detect verbs and nearby relation particles/prepositions.
- ``nltk.stem.WordNetLemmatizer`` normalizes verb tokens through WordNet instead
  of a project-maintained override table.
- ``stopwordsiso.stopwords`` supplies language-specific stop
  words for candidate phrase filtering.
"""

import re

import nltk
from nltk.stem import WordNetLemmatizer

from generate_pipeline.clients.wikidata_client import find_entity_id_by_name

from stopwordsiso import stopwords as load_stopwords


MAX_ENTITIES = 50
_STOP_WORD_CACHE: dict[str, set[str]] = {}
_LEMMATIZER = WordNetLemmatizer()


def _tokens(text: str) -> list[str]:
    """Return simple word tokens using ``re.findall`` from the standard library."""
    return re.findall(r"[\w]+(?:-[\w]+)*", text)


def _token_matches(text: str) -> list[re.Match]:
    """Return regex match objects so token text and character spans stay aligned."""
    return list(re.finditer(r"[\w]+(?:-[\w]+)*", text))


def _stop_words(lang: str) -> set[str]:
    """Load and cache stop words through the optional ``stopwordsiso`` library."""
    if lang not in _STOP_WORD_CACHE:
        if load_stopwords is None:
            _STOP_WORD_CACHE[lang] = set()
        else:
            _STOP_WORD_CACHE[lang] = {
                word.casefold() for word in load_stopwords(lang)
            }
    return _STOP_WORD_CACHE[lang]


def _candidate_phrases(text: str, lang: str) -> list[str]:
    """Return likely entity phrases from natural-language text."""
    phrases: list[str] = []
    stop_words = _stop_words(lang)

    capitalized_pattern = r"\b[A-Z][\w-]*(?:\s+(?:[A-Z][\w-]*|of|and|the|&))*"
    phrases.extend(match.group(0).strip() for match in re.finditer(capitalized_pattern, text))

    tokens = _tokens(text)
    for index, token in enumerate(tokens):
        if token.casefold() in stop_words:
            continue
        phrases.append(token)
        if index + 1 < len(tokens):
            next_token = tokens[index + 1]
            if next_token.casefold() not in stop_words:
                phrases.append(f"{token} {next_token}")

    seen = set()
    unique_phrases = []
    for phrase in phrases:
        phrase = phrase.strip(" ,;:()[]")
        key = phrase.casefold()
        if not phrase or key in seen or key in stop_words:
            continue
        seen.add(key)
        unique_phrases.append(phrase)
    return unique_phrases


def _phrase_span(text: str, phrase: str) -> tuple[int, int] | None:
    """Locate a phrase using ``re.search`` with escaped phrase text."""
    match = re.search(rf"\b{re.escape(phrase)}\b", text, flags=re.IGNORECASE)
    if match:
        return match.span()
    return None


def _sentence_start(text: str, index: int) -> int:
    """Return the start offset of the sentence containing ``index``."""
    boundary = max(text.rfind(".", 0, index), text.rfind("!", 0, index), text.rfind("?", 0, index))
    return 0 if boundary == -1 else boundary + 1


def _sentence_end(text: str, index: int) -> int:
    """Return the end offset of the sentence containing ``index``."""
    boundaries = [position for position in (text.find(".", index), text.find("!", index), text.find("?", index)) if position != -1]
    return min(boundaries) if boundaries else len(text)


def _pos_tag(tokens: list[str]) -> list[tuple[str, str]]:
    """Tag tokens with ``nltk.pos_tag``, downloading the model when needed."""
    try:
        return nltk.pos_tag(tokens)
    except LookupError:
        nltk.download("averaged_perceptron_tagger_eng", quiet=True)
        return nltk.pos_tag(tokens)


def _tag_text(text: str) -> list[tuple[re.Match, str]]:
    """Return token regex matches paired with NLTK Penn Treebank POS tags."""
    matches = _token_matches(text)
    tagged_tokens = _pos_tag([match.group(0) for match in matches])
    return [
        (match, tag)
        for match, (_token, tag) in zip(matches, tagged_tokens)
    ]


def _verb_lemma(token: str) -> str:
    """Normalize a verb with NLTK's ``WordNetLemmatizer``."""
    try:
        return _LEMMATIZER.lemmatize(token.casefold(), pos="v")
    except LookupError:
        nltk.download("wordnet", quiet=True)
        return _LEMMATIZER.lemmatize(token.casefold(), pos="v")


def _verb_matches(text: str) -> list[tuple[str, str, int, int]]:
    """Return POS-tagged verb tokens with their spans."""
    return [
        (match.group(0), tag, match.start(), match.end())
        for match, tag in _tag_text(text)
        if tag.startswith("VB")
    ]


def _verb_token_starts(text: str) -> set[int]:
    """Return absolute start offsets for tokens used as verbs."""
    starts = set()
    sentence_start = 0
    while sentence_start < len(text):
        sentence_end = _sentence_end(text, sentence_start)
        sentence = text[sentence_start:sentence_end]
        for _token, _tag, start, _end in _verb_matches(sentence):
            starts.add(sentence_start + start)
        sentence_start = sentence_end + 1
    return starts


def _predicate_from_parts(*parts: str) -> str:
    """Build a camelCase predicate from library-selected relation tokens."""
    clean_parts = []
    for part in parts:
        clean_parts.extend(re.findall(r"[A-Za-z][A-Za-z0-9]*", part))
    if not clean_parts:
        return ""
    first, *rest = [part.casefold() for part in clean_parts]
    return first + "".join(part.capitalize() for part in rest)


def _relation_particle(text_between_verb_and_phrase: str) -> str:
    """Return a nearby NLTK-tagged preposition or particle for a relation."""
    if "," in text_between_verb_and_phrase or ";" in text_between_verb_and_phrase:
        return ""

    tagged_matches = _tag_text(text_between_verb_and_phrase)
    for match, tag in reversed(tagged_matches):
        if tag in {"IN", "RP", "TO"}:
            return match.group(0).casefold()
    return ""


def _best_verb_before_phrase(text: str, cutoff: int) -> tuple[str, int, int] | None:
    """Choose the nearest useful verb before an entity phrase."""
    verbs = [
        (token, tag, start, end)
        for token, tag, start, end in _verb_matches(text)
        if end <= cutoff
    ]
    if not verbs:
        return None

    token, _tag, start, end = verbs[-1]
    return _verb_lemma(token), start, end


def _predicate_from_verb_context(verb: str, between_verb_and_phrase: str) -> str:
    particle = _relation_particle(between_verb_and_phrase)
    parts = (verb, particle) if particle else (verb,)
    return _predicate_from_parts(*parts)


def _verb_relationship(text: str, phrase: str) -> str | None:
    span = _phrase_span(text, phrase)
    if span is None:
        return None

    sentence_start = _sentence_start(text, span[0])
    context = text[sentence_start:span[1]]
    phrase_start = span[0] - sentence_start
    best_verb = _best_verb_before_phrase(context, phrase_start)
    if best_verb is None:
        return None

    verb, _verb_start, verb_end = best_verb
    predicate = _predicate_from_verb_context(verb, context[verb_end:phrase_start])
    return predicate or None


def _resolve_phrase(phrase: str, lang: str, source_id: str) -> str | None:
    entity_id = find_entity_id_by_name(phrase, lang)
    if entity_id and entity_id != source_id:
        return entity_id
    return None


def extract_entities_and_relations(
    description: str, lang: str, source_id: str
) -> tuple[set[str], list[tuple[str, str, str]]]:
    """Resolve description phrases to Wikidata entity IDs."""
    if not description.strip():
        return set(), []

    entity_ids = set()
    relations = []
    verb_token_starts = _verb_token_starts(description)

    for phrase in _candidate_phrases(description, lang):
        span = _phrase_span(description, phrase)
        if span and span[0] in verb_token_starts:
            continue
        entity_id = _resolve_phrase(phrase, lang, source_id)
        if entity_id:
            entity_ids.add(entity_id)
            relationship = _verb_relationship(description, phrase)
            if relationship:
                relations.append((source_id, relationship, entity_id))
        if len(entity_ids) >= MAX_ENTITIES:
            break

    return entity_ids, relations
