# Step 1: Generate Wikidata Description RDF

This step queries Wikidata, builds short text descriptions, and appends two rows to
the base CSV with these columns:

```text
identifier,description,rdf,triples
```

The Turtle graph is stored in the CSV `rdf` column.

Each CSV `description` contains exactly 2 cleaned introductory Wikipedia phrases
from one matched Wikidata entity. The two entities are stored independently as
`identifier_01` and `identifier_02`, each with its own RDF. If fewer than 2
different entities have 2 Wikipedia phrases each, no rows are written.

The text is converted to subject-predicate-object triples first. When a resolved
description phrase has a nearby verb in the text, NLTK POS tagging and WordNet
are used to identify that verb, and the verb becomes the predicate. The Turtle
graph in `rdf` is then serialized from those extracted triples.
The readable triples are materialized before RDF construction. The RDF contains
only the extracted relationships and the labels needed for their subjects and
objects; Wikidata `P31` (`instance of`) classes are not queried or added.

## Run

From the project root:

```powershell
python -m pip install -r requirements.txt
```

```powershell
python generate/src/main.py "Mango"
```

Pass two explicit names to use only the first Wikidata result for each. Their
normalized names are joined with `-` in the output identifier:

```powershell
python generate/src/main.py car automobile
# identifiers: Car-Automobile_01 and Car-Automobile_02
```

The project-level `synonyms.txt` stores `first,second` pairs, one per line:

```powershell
Get-Content synonyms.txt | Where-Object { $_.Trim() } | ForEach-Object {
    $pair = $_ -split ',', 2
    python generate/src/main.py $pair[0].Trim() $pair[1].Trim()
}
```

Generate multiple rows by running the command once per entity:

```powershell
python generate/src/main.py "Grape"
python generate/src/main.py "Mango"
python generate/src/main.py "Watermelon"
python generate/src/main.py "banana"
python generate/src/main.py "Cocos nucifera"
```

Generate rows from a text file with one term per line:

```powershell
Get-Content ambiguous_words.txt | Where-Object { $_.Trim() } | ForEach-Object {
    python generate/src/main.py $_.Trim() --csv data/wikidata_base.csv
}
```

The command writes two rows to a CSV with `identifier,description,rdf,triples`
columns. `identifier` stores the requested entity name plus `_01` or `_02`, such
as `Jaguar_01`. The `rdf`
column stores Turtle, and the `triples` column is a JSON list where each item is
`[subject, predicate, object]` extracted from the text, using readable entity
labels when available.

The two creation-time records are merged into one row in
`data/wikidata_graphs.csv`: `_01` and `_02` lose their suffix,
their descriptions and triples are concatenated, and their RDF graphs are
combined with one prefix block. Use `--graph-csv` to choose another path. This
file is produced by the generation step, not by enrichment.

The generation order is:

1. Extract and resolve candidate relationships from the Wikipedia phrases.
2. Remove duplicate and redundant relationships.
3. Convert the remaining relationships to readable triples.
4. Serialize only those relationships as Turtle RDF.
5. Append the description, readable triples, and RDF to the CSV.

## Options

```powershell
python generate/src/main.py "Watermelon" --csv data/wikidata_base.csv
```

| Option | Default | Description |
| --- | --- | --- |
| `names` | 1 or 2 required | One ambiguous name, or two names whose first Wikidata matches are used. |
| `--csv` | `data/wikidata_base.csv` | CSV file to append generated rows to. |
| `--graph-csv` | `data/wikidata_graphs.csv` | Dedicated CSV containing identifier, full description, RDF, and triples. |

The `data/` directory is created automatically when needed.

The pipeline uses English for Wikipedia text, Wikidata labels, stop words, POS
tagging, and WordNet lemmatization. The language is not configurable from the
command line.

The CSV output is append-only. Delete or rename the output file first if you want
a fresh dataset. Before making any Wikipedia or Wikidata requests, the command
checks whether either normalized suffixed `identifier` already exists in the output CSV.
The comparison ignores surrounding whitespace and letter case. Existing
identifiers are skipped without changing the file.

## Flow

The generation process is also documented as PlantUML in
[`generate_flow.puml`](docs/generate_flow.puml).
The extraction libraries and helper functions are documented in
[`extraction_libraries.md`](docs/extraction_libraries.md).

```plantuml
@startuml
start
:Read entity name and options;
:Search Wikidata for candidate item IDs;
while (Need 2 entities with 2 phrases each?) is (yes)
  :Fetch Wikidata entity;
  :Fetch matching Wikipedia title;
  :Fetch and clean 2 intro phrases;
  if (Two unique phrases?) then (yes)
    :Extract phrase entities and verb predicates;
    :Fetch labels;
    :Build readable triples from extracted relations;
    :Build Turtle RDF only from those triples;
  endif
endwhile (no)
:Combine each text's phrases into one description;
:Append one identifier, description, rdf, triples row per text;
stop
@enduml
```

## Files

| File | Responsibility |
| --- | --- |
| `generate/src/main.py` | Command-line entry point for this step. |
| `generate/src/generate_pipeline/cli.py` | Generation orchestration and CLI implementation. |
| `generate/src/generate_pipeline/models.py` | Immutable generated-text data model. |
| `generate/src/generate_pipeline/clients/` | Wikidata and Wikipedia API clients. |
| `generate/src/generate_pipeline/extraction/` | Description term and verb-derived relation extraction. |
| `generate/src/generate_pipeline/io/` | CSV rows, Turtle RDF, and explicit triple list writers. |

The orchestration is split into reusable helpers for input normalization,
candidate lookup, phrase selection, text construction, graph combination, and
output writing. `extract_relations` is the public extraction boundary: it
returns only relations that can contribute to the generated graph.
