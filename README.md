# Wikidata Description RDF Pipeline

This project has two steps:

1. Generate a base Wikidata description/RDF CSV.
2. Enrich that CSV with graph traversal checks and SPARQL queries.

For example, a description such as `species of plant` is read word by word.
Resolved Wikidata entities are linked to the original entity as
`subject, predicate, object` triples first, and those triples are then serialized
as Turtle RDF. The RDF contains only relationships extracted from the Wikipedia
text. The generation step does not query or add Wikidata `P31` (`instance of`)
classes.

Within the evaluation workspace, `data/wikidata_graphs.csv` is the shared input
for the three construction pipelines. Each combined description is sent to the
prompt, ontology, and hybrid APIs so their RDF output can be compared on the
same source text. The enriched SPARQL CSVs provide task-oriented checks for the
evaluation notebook.

## Requirements

- Python 3.10 or newer
- Internet access to the public Wikidata and Wikipedia APIs
- Python packages `nltk`, `stopwordsiso`, and `rdflib`

## Quick start

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

The commands below are run from the repository root. Generation requires live
Wikipedia and Wikidata access; the unit tests are offline.

On first use, NLTK may also download its English POS tagger and WordNet data. Set
`WIKIDATA_USER_AGENT` before running generation to identify your API client.

Run the generation step once per entity:

```powershell
python generate/src/main.py "Grape"
python generate/src/main.py "Mango"
python generate/src/main.py "Watermelon"
```

The generator also accepts two explicit names. In this mode it uses only the
first Wikidata search result for each name and joins the names with `-` for the
CSV identifier:

```powershell
python generate/src/main.py car automobile
# identifier: Car-Automobile
```

[`synonyms.txt`](synonyms.txt) contains synonym pairs as `first,second`, one
pair per line. Process the file with:

```powershell
Get-Content synonyms.txt | Where-Object { $_.Trim() } | ForEach-Object {
    $pair = $_ -split ',', 2
    python generate/src/main.py $pair[0].Trim() $pair[1].Trim()
}
```

Run the generation step for every term in a text file such as
`ambiguous_words.txt`, with one input term per line:

```powershell
Get-Content ambiguous_words.txt | Where-Object { $_.Trim() } | ForEach-Object {
    python generate/src/main.py $_.Trim()
}
```

Then enrich the generated CSV with SPARQL queries:

```powershell
python enrich/src/main.py
```

Default outputs:

```text
data/wikidata_base.csv
data/wikidata_graphs.csv
data/wikidata_label_sparql.csv
data/wikidata_id_sparql.csv
```

Generated files under `data/` are local artifacts and are excluded from Git.
A fresh clone therefore requires generation and enrichment before running the
evaluation notebooks. Keep a copy of the exact CSVs used for an experiment if
you need to reproduce its results; live source content can change between runs.

The current `ambiguous_words.txt` starts with `bass` and `mouse` in place of
`jaguar` and `mango`. These are generation inputs; changing the list does not
remove rows from an existing append-only dataset.

The generation step is append-only. Delete or rename existing output files first
if you want a fresh dataset. Before making any Wikipedia or Wikidata requests,
the generator checks the output CSV. If its normalized `identifier` already
exists, that input is skipped and the CSV is not changed.

## Step documentation

Supporting implementation notes and PlantUML flow sources:

- [Extraction libraries](generate/docs/extraction_libraries.md)
- [Generation flow](generate/docs/generate_flow.puml)
- [Enrichment flow](enrich/docs/enrich_flow.puml)

Run the offline unit tests with:

```powershell
python -m unittest discover -s generate/tests
python -m unittest discover -s enrich/tests
```

## Base CSV Output

The generated base CSV contains these columns:

```text
identifier,description,rdf,triples
```

`identifier` contains the requested entity name plus `_01` or `_02`, such as
`Jaguar_01`. Each `description` contains exactly 2 cleaned introductory
Wikipedia phrases from one matched Wikidata entity. The two matched entities
are stored as independent rows. Quoted and parenthesized text is removed, and
Wikidata descriptions are not used as fallback prose. The companion
`wikidata_graphs.csv` combines each pair into one four-phrase
record without the suffix.
`triples` contains a JSON list of text-extracted triples, where each item is
`[subject, predicate, object]` using readable entity labels when available.
When a resolved description phrase has a nearby verb in the text, NLTK POS
tagging and WordNet are used to identify that verb, and the verb becomes the
predicate.
The readable `triples` list is built before RDF serialization. `rdf` then
contains a self-contained Turtle representation of only those extracted
relationships, plus the labels needed to identify their subjects and objects.
It includes the `rdfs`, `wd`, and `kg` prefixes, but no externally fetched
class/type triples.

## Enriched CSV Output

The enriched CSV is a separate reference CSV. It does not duplicate the base
`description`, `rdf`, or `triples` values. It contains:

```text
identifier,description_identifier,question,query_type,sparql,answer
```

The directed ID checks are stored in a companion CSV:

```text
identifier,description_identifier,question,answer_id,id_sparql
```

The generation step also merges each `_01`/`_02` pair into one complete source
record with the base identifier, concatenated text, combined Turtle RDF, and
merged readable triples:

```text
identifier,description,rdf,triples
```

`identifier` sanitizes the source identifier and appends a question number,
such as `Jaguar_01_01` for source row `Jaguar_01`.
`description_identifier` references the `identifier` from the generated base
CSV. Each enriched row contains one `question`, its `query_type`, one `sparql`
query, and an `answer` encoded as a JSON list. The first row for each source
evaluates linked entities and the second evaluates relationship predicates.
`answer_id`
stores the expected Wikidata identifier
when available, while `id_sparql` contains an additional ID-focused query. The
main `sparql` query selects a source entity with a case-insensitive `REGEX` over
its label, then returns every entity directly connected to it by an incoming or
outgoing edge, without restricting the relationship predicate. The separate
`id_sparql` query uses the original directed ID path: a fixed source IRI, a
variable predicate, and a filter for the expected answer IRI.
If the source label is absent from an evaluated KG, label queries fall back to
graph-wide entity or predicate candidates so the external evaluator can apply
its generic matching. The main `answer` is populated from the query's actual local result. The
directed ID query must also return its expected Q-ID; a validation failure
aborts enrichment instead of writing a partially validated output.

## RDF Example

The CSV `rdf` column stores Turtle with Wikidata IDs and labels. A simplified
example:

```turtle
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix wd: <http://www.wikidata.org/entity/> .
@prefix kg: <https://example.org/wikidata-description/> .

wd:Q1054564 rdfs:label "Mango"@en ;
    kg:was wd:Q488205 .

wd:Q488205 rdfs:label "singer-songwriter"@en .
```

The resolved IDs are Wikidata item IDs (`wd:Q...`).
There is no `rdf:type`/`a` statement because the graph is derived only from the
readable relationships extracted from the source text.
