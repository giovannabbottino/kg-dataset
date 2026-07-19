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

## Requirements

- Python 3.9 or newer
- Internet access to the public Wikidata API
- Python packages in `requirements.txt`

## Pipeline Usage

Install dependencies:

```powershell
pip install -r requirements.txt
```

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
data/wikidata_description_rdf.csv
data/wikidata_description_rdf_enriched.csv
```

The generation step is append-only. Delete or rename existing output files first
if you want a fresh dataset. Before making any Wikipedia or Wikidata requests,
the generator checks the output CSV. If its normalized `identifier` already
exists, that input is skipped and the CSV is not changed.

## Step Documentation

Each step has its own docs folder with a README and PlantUML flow diagram:

- [Generate docs](generate/README.md)
- [Generate PlantUML flow](generate/docs/generate_flow.puml)
- [Enrich docs](enrich/README.md)
- [Enrich PlantUML flow](enrich/docs/enrich_flow.puml)

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

`identifier` contains the requested entity name used to generate the row, such
as `Jaguar`.
`description` contains exactly 4 cleaned introductory Wikipedia phrases: 2
phrases from each of 2 different matched Wikidata entities. Quoted and
parenthesized text is removed. Wikidata descriptions are not used as fallback
prose.
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
identifier,description_identifier,question,sparql,answer,answer_id,id_sparql
```

`identifier` uses the source entity plus a question number, such as
`Jaguar_01`. `description_identifier` references the `identifier` from the
generated base CSV. Each enriched row contains one `question`, one `sparql`
query, and one `answer`. `answer_id` stores the expected Wikidata identifier
when available, while `id_sparql` contains an additional ID-focused query. The
The main `sparql` query matches the expected subject and answer labels and
requires a direct or two-hop connection. The separate `id_sparql` query
addresses every entity in the selected path directly through
its Wikidata ID and does not infer IDs from labels or constrain predicate names.
Each query is executed against the source row's Turtle RDF and must return the
expected answer before it is written to the enriched CSV.

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

## Project structure

| File | Responsibility |
| --- | --- |
| `generate/src/generate_pipeline/` | Step 1 package: Wikidata lookup, description extraction, CSV/RDF generation. |
| `generate/src/generate_pipeline/clients/` | Wikidata and Wikipedia API clients. |
| `generate/src/generate_pipeline/extraction/` | Description phrase, entity, and relation extraction. |
| `generate/src/generate_pipeline/io/` | CSV and Turtle RDF output helpers. |
| `generate/tests/` | Offline unit tests for generation helpers. |
| `generate/docs/` | Generation process docs and PlantUML flow. |
| `enrich/src/enrich_pipeline/` | Step 2 package: RDF parsing and SPARQL enrichment. |
| `enrich/src/enrich_pipeline/parsing/` | Turtle parsing for generated RDF. |
| `enrich/src/enrich_pipeline/evaluation/` | Graph traversal question and SPARQL generation. |
| `enrich/src/enrich_pipeline/io/` | Enrichment CSV writer. |
| `enrich/src/enrich_pipeline/models/` | Shared dataclasses for enrichment. |
| `enrich/tests/` | Offline unit tests for enrichment helpers. |
| `enrich/docs/` | Enrichment process docs and PlantUML flow. |
| `data/wikidata_description_rdf.csv` | Base generated CSV. |
| `data/wikidata_description_rdf_enriched.csv` | Enriched CSV with SPARQL query columns. |
