# Exploratory Analysis Plan

## Purpose

This folder defines a reproducible exploratory data analysis (EDA) plan for the
Wikidata Description RDF dataset. The analysis should determine whether the
dataset is structurally complete, internally consistent, semantically useful,
and suitable for evaluating knowledge-graph construction and SPARQL question
answering.

The EDA is diagnostic. It should describe the dataset and surface risks before
any model comparison or benchmark scoring is performed.

## Dataset model

The pipeline produces four related CSV files:

| File | Unit of observation | Expected role |
| --- | --- | --- |
| `data/wikidata_base.csv` | One resolved meaning (`_01` or `_02`) | Source description, RDF graph, and readable triples |
| `data/wikidata_graphs.csv` | One ambiguous term or synonym-pair root | Combination of the two corresponding base records |
| `data/wikidata_label_sparql.csv` | One label-oriented question | Entity- or predicate-retrieval query and expected answer list |
| `data/wikidata_id_sparql.csv` | One directed ID check | Query for a specific expected Wikidata Q-ID |

Initial profiling found 80 base records forming 40 complete pairs, 40 combined
graphs, 160 label questions (80 `entity`, 80 `predicate`), and 79 ID questions.
`Mustang_02` is the only base record without an ID-question row. This is an
investigation lead, not a conclusion that the row is defective.

## Core exploratory questions

### 1. Dataset shape and structural completeness

1. How many rows, columns, unique identifiers, and missing values does each
   file contain?
2. Are identifiers unique within each file and syntactically consistent with
   their expected naming convention?
3. Does every root identifier have exactly one `_01` and one `_02` base row?
4. Does every complete base pair map to exactly one row in
   `wikidata_graphs.csv`?
5. Does every base row have exactly one `entity` question and one `predicate`
   question?
6. Which base rows lack an ID question, and is the absence explained by the
   graph content or by generation failure?
7. Are there orphaned foreign keys in `description_identifier`?

### 2. Description characteristics

1. What are the distributions of description length in characters, words,
   sentences, and cleaned introductory phrases?
2. Do base descriptions satisfy the documented two-phrase expectation, and do
   combined descriptions satisfy the four-phrase expectation?
3. Are any descriptions exact or near duplicates across identifiers?
4. How much lexical overlap exists between the `_01` and `_02` meanings of the
   same root?
5. Which terms are most and least ambiguous based on description similarity?
6. Are unusual punctuation, encoding artifacts, empty fragments, or residual
   parenthetical/quoted passages present?

### 3. Triple and graph structure

1. How many triples, unique subjects, predicates, objects, and Wikidata items
   occur per base and combined graph?
2. What are the minimum, median, upper-tail, and maximum graph sizes, and which
   records are outliers?
3. What is the predicate-frequency distribution? Is it dominated by generic
   predicates such as `be`?
4. How often are triples duplicated exactly or after case/whitespace
   normalization?
5. Do readable triples and RDF edges agree one-to-one after resolving labels?
6. Are all triple subjects and objects represented by valid RDF resources and,
   where expected, `rdfs:label` statements?
7. Are any self-loops, isolated nodes, disconnected components, or repeated
   subject-predicate-object edges present?
8. Does each combined graph equal the union of its `_01` and `_02` source
   graphs, without lost or newly introduced triples?
9. How much do the two meanings in a combined graph overlap in nodes,
   predicates, and edges?

### 4. Entity-resolution and semantic quality

1. Are resolved Wikidata labels semantically supported by the source
   description phrase that produced them?
2. What proportion of triples appear clearly correct, plausible but ambiguous,
   or clearly incorrect under a manually reviewed sample?
3. Which error types dominate: wrong entity sense, token-fragment resolution,
   overly generic concepts, named-entity confusion, number/date resolution, or
   predicate extraction errors?
4. Are semantic errors concentrated in particular predicates, parts of speech,
   description lengths, or graph sizes?
5. Do entities associated with ambiguous words have a higher mismatch rate
   than synonym-pair entities?
6. Do suspicious labels (for example, unrelated proper names or medical terms)
   recur across many graphs, suggesting systematic resolver bias?
7. Does pruning remove genuinely redundant objects without deleting distinct
   concepts?

### 5. RDF validity and consistency

1. Can every Turtle document be parsed successfully?
2. Are only the documented namespaces (`rdfs`, `wd`, and `kg`) used?
3. Are Wikidata resources formatted as valid `Q` identifiers?
4. Are predicate local names valid, stable, and normalized consistently?
5. Are forbidden or unintended statements such as `rdf:type`/`a` present?
6. Does each graph contain the expected focal entity and its label?
7. Are labels unique enough to identify the intended focal entity, especially
   when two resources share the same surface form?

### 6. Question and answer coverage

1. Are label questions balanced between `entity` and `predicate` query types?
2. Are question identifiers unique and sequential within each source record?
3. Does each question mention or unambiguously refer to its intended focal
   entity?
4. Are expected answers valid JSON lists, non-empty, unique, and sorted as
   intended?
5. Does every entity answer correspond to a direct incoming or outgoing graph
   neighbor?
6. Does every predicate answer correspond to a direct edge incident on the
   focal entity?
7. How many expected answers occur per question, and how skewed is this
   distribution?
8. Do questions leak expected answers or graph IDs through their wording?
9. Are natural-language templates sufficiently varied, or could evaluation be
   solved by template memorization?

### 7. SPARQL correctness and robustness

1. Can every SPARQL query be parsed and executed against its corresponding RDF
   graph?
2. Does each query reproduce its stored expected answer exactly, as a set, and
   not merely under permissive substring matching?
3. Do ID queries return the declared `answer_id` with the intended direction
   and edge scope?
4. Do label queries select the correct focal subject when labels collide?
5. How often is the canonical-ID tie-break required, and what happens when it
   is unavailable?
6. Do `LIMIT 1`, fallback selection, optional labels, or bidirectional unions
   create nondeterministic or overly permissive results?
7. Are namespace declarations and excluded label predicates consistent across
   all generated queries?
8. Are query complexity, length, and execution time unusually high for certain
   graph structures?

### 8. Evaluation readiness and bias

1. What are the distributions of roots, senses, graph sizes, predicates,
   answer-set sizes, and question types?
2. Are train/development/test splits possible without placing two senses of the
   same root, or their combined graph, in different splits?
3. Are duplicate descriptions, entities, edges, or question templates likely
   to cause leakage across splits?
4. Does the benchmark overrepresent easy direct-neighbor retrieval relative to
   difficult semantic graph construction?
5. Which metrics should be reported separately by query type, graph size,
   ambiguity level, and semantic-quality tier?
6. How sensitive would benchmark scores be to noisy ground-truth triples or
   permissive answer matching?

## Execution plan

### Phase 1 — Ingestion and schema audit

- Load all CSVs with explicit UTF-8 handling.
- Record row counts, column types, missingness, uniqueness, and identifier
  patterns.
- Validate cross-file keys and the expected 2:1:4 relationship among base
  rows, combined graphs, and label questions.
- Produce an exceptions table rather than silently dropping malformed rows.

### Phase 2 — Content profiling

- Parse every `triples` and `answer` JSON value.
- Parse every Turtle graph and SPARQL query.
- Compute text-length, graph-size, vocabulary, predicate, answer-set, and query
  complexity distributions.
- Identify outliers using both quantiles and interpretable absolute thresholds.

### Phase 3 — Cross-file reconciliation

- Reconstruct every combined record from its two source rows.
- Compare description concatenation, RDF union, and readable-triple union.
- Re-execute label and ID queries locally and compare result sets with stored
  answers.
- Investigate all missing, orphaned, duplicated, or non-reproducible records.

### Phase 4 — Semantic quality review

- Draw a reproducible stratified sample across roots, graph-size quartiles,
  frequent predicates, and suspicious entity labels.
- Have reviewers label each sampled triple as `correct`, `plausible`,
  `incorrect`, or `unclear`, with an error-category field.
- Use at least two reviewers for a shared subset and report inter-annotator
  agreement before extrapolating error rates.

### Phase 5 — Evaluation-risk assessment

- Quantify template repetition, label collisions, answer leakage, split leakage,
  and permissive-match effects.
- Compare exact-set scoring with the pipeline's normalized/containment matching.
- Define safe grouping keys for later data splits (`root identifier` at a
  minimum).

### Phase 6 — Reporting

- Summarize findings in an answer-first report.
- Separate confirmed defects from expected exceptions and unresolved risks.
- Provide machine-readable issue tables with file, identifier, check, observed
  value, expected value, and severity.
- End with prioritized recommendations for dataset repair and benchmark use.

## Recommended outputs

1. `eda_summary.md` — concise findings, implications, and recommendations.
2. `profile_tables/` — CSV tables for distributions and detected exceptions.
3. `figures/` — compact charts for graph size, predicate frequency, text
   length, answer-set size, and error taxonomy.
4. `semantic_review_sample.csv` — reproducible annotation sample and rubric.
5. `data_quality_issues.csv` — one row per confirmed or suspected issue.
6. `eda_analysis.ipynb` or an equivalent reproducible script — all calculations
   required to rebuild the report.

## Quality gates

The dataset should not be declared evaluation-ready until:

- all four schemas and cross-file relationships are validated;
- all JSON, Turtle, and SPARQL content parses successfully;
- stored answers are reproducible from their assigned graphs;
- combined graphs reconcile with their source pairs;
- the missing ID-query case is explained;
- semantic error rates and dominant error classes are estimated from a
  stratified review; and
- a leakage-safe split strategy is documented.

## Analysis principles

- Treat identifiers and Wikidata Q-IDs as strings, not numbers.
- Compare answer collections as sets unless order is explicitly meaningful.
- Preserve incoming and outgoing edge direction during diagnostics.
- Report both record-weighted and root-weighted statistics.
- Do not treat successful parsing as evidence of semantic correctness.
- Do not silently repair source data during EDA; record proposed fixes
  separately.
