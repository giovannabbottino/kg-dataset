# Extraction Libraries and Functions

The generation step uses library-backed text analysis instead of hand-written
word lists for verb and particle detection.

## Python Standard Library

| Library or function | Used in | Purpose |
| --- | --- | --- |
| `re.findall` | `_tokens`, `_predicate_from_parts` | Tokenizes words and builds clean predicate names from selected text. |
| `re.finditer` | `_token_matches` | Keeps each token aligned with its character span in the original text. |
| `re.search` | `_phrase_span` | Finds candidate phrase locations before relation extraction. |
| `str.find`, `str.rfind` | `_sentence_start`, `_sentence_end` | Locates sentence boundaries around a candidate phrase. |

## NLTK

| Library or function | Used in | Purpose |
| --- | --- | --- |
| `nltk.pos_tag` | `_pos_tag`, `_tag_text`, `_verb_matches`, `_relation_particle` | Assigns Penn Treebank POS tags. Verb tags (`VB*`) identify predicate verbs. Preposition, particle, and infinitive tags (`IN`, `RP`, `TO`) identify relation particles without maintaining a custom word list. |
| `nltk.download` | `_pos_tag`, `_verb_lemma` | Downloads the required NLTK tagger or WordNet corpus when missing. |
| `WordNetLemmatizer.lemmatize` | `_verb_lemma` | Normalizes verbs with WordNet, replacing the previous custom verb override dictionary. |

## stopwordsiso

| Library or function | Used in | Purpose |
| --- | --- | --- |
| `stopwordsiso.stopwords` | `_stop_words`, `_candidate_phrases` | Loads and caches language-specific stop words so common words are not resolved as Wikidata entity phrases. |

## Project Functions

| Function | Purpose |
| --- | --- |
| `extract_relations` | Public extraction entry point. It resolves candidate phrases to Wikidata IDs and emits `(subject, predicate, object)` relation tuples. |
| `_candidate_phrases` | Produces candidate entity phrases from capitalized text and stop-word-filtered one- or two-token phrases. |
| `_verb_relationship` | Finds the nearest useful verb before a resolved entity phrase and converts it into a predicate. |
| `_relation_particle` | Uses NLTK POS tags to add a nearby preposition or particle to the predicate, such as converting a tagged context into `knownFor` when the text supports it. |
| `_resolve_phrase` | Calls the Wikidata client to resolve a phrase to an item ID while avoiding self-links. |
