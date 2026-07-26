import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rdflib import Graph


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from enrich_pipeline.evaluation import graph_traversal
from enrich_pipeline.evaluation.query_validation import query_returns_answer
from enrich_pipeline.io import enrichment_csv
from enrich_pipeline.models import Label, Triple
from enrich_pipeline.parsing.turtle import parse_turtle


SAMPLE_RDF = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix wd: <http://www.wikidata.org/entity/> .
@prefix kg: <https://example.org/wikidata-description/> .

wd:Q1 a wd:Q5 ;
    rdfs:label "Mango"@en ;
    kg:is wd:Q2 .

wd:Q2 rdfs:label "fruit"@en .
wd:Q5 rdfs:label "class"@en .
"""
EXPECTED_LABEL_ANSWER = '["fruit"]'


class EnrichTests(unittest.TestCase):
    def test_encode_answers_has_stable_case_insensitive_order(self):
        answer = enrichment_csv.encode_answers(["community", "fruit", "Community"])

        self.assertEqual('["Community", "community", "fruit"]', answer)

    def test_generates_at_most_two_queries_per_rdf(self):
        labels = {
            "wd:Q1": Label("Mango", "en"),
            "wd:Q2": Label("fruit", "en"),
            "wd:Q3": Label("food", "en"),
            "wd:Q4": Label("plant", "en"),
        }
        triples = [
            Triple("wd:Q1", "kg:is", "wd:Q2"),
            Triple("wd:Q1", "kg:is", "wd:Q3"),
            Triple("wd:Q1", "kg:is", "wd:Q4"),
        ]

        items = graph_traversal.build_graph_traversal_items(
            labels, {"wd:Q1"}, triples, "Mango is fruit, food, and a plant."
        )

        self.assertEqual(2, len(items))

    def test_second_label_query_evaluates_predicates(self):
        labels = {
            "wd:Q1": Label("Mango", "en"),
            "wd:Q2": Label("fruit", "en"),
            "wd:Q3": Label("food", "en"),
            "wd:Q4": Label("India", "en"),
        }
        triples = [
            Triple("wd:Q1", "kg:is", "wd:Q2"),
            Triple("wd:Q1", "kg:is", "wd:Q3"),
            Triple("wd:Q1", "kg:growsIn", "wd:Q4"),
        ]

        items = graph_traversal.build_graph_traversal_items(
            labels, {"wd:Q1"}, triples, "Mango is fruit and grows in India."
        )

        self.assertEqual(2, len(items))
        self.assertEqual("entity", items[0].query_type)
        self.assertEqual("predicate", items[1].query_type)
        self.assertNotIn("REGEX(", items[0].sparql)
        self.assertNotIn("REGEX(", items[1].sparql)
        self.assertIn("MAX(?canonicalMatch)", items[0].sparql)
        self.assertIn("SUM(?edgeWeight)", items[0].sparql)
        self.assertIn("<http://www.wikidata.org/entity/Q1>", items[0].sparql)
        self.assertIn('BIND("outgoing" AS ?direction)', items[0].sparql)
        self.assertIn('BIND("incoming" AS ?direction)', items[0].sparql)
        self.assertIn("REPLACE(STR(?predicate)", items[1].sparql)
        self.assertNotIn("'is'", items[0].sparql)
        self.assertEqual("wd:Q2", items[0].answer_id)
        self.assertEqual("", items[1].answer_id)

    def test_main_query_does_not_depend_on_hyphenated_source_label(self):
        rdf = SAMPLE_RDF.replace('"Mango"@en', '"singer-songwriter"@en')
        labels, roots, triples = parse_turtle(rdf)
        item = graph_traversal.build_graph_traversal_items(labels, roots, triples)[0]

        self.assertNotIn("singer-songwriter", item.sparql)
        self.assertNotIn("REGEX(", item.sparql)
        self.assertTrue(query_returns_answer(rdf, item.sparql, EXPECTED_LABEL_ANSWER))

    def test_main_query_does_not_use_multiword_label_tokens(self):
        rdf = SAMPLE_RDF.replace('"Mango"@en', '"Mango Company"@en')
        labels, roots, triples = parse_turtle(rdf)
        entity_item, predicate_item = graph_traversal.build_graph_traversal_items(
            labels, roots, triples
        )

        self.assertNotIn("REGEX(", entity_item.sparql)
        self.assertNotIn("REGEX(", predicate_item.sparql)
        self.assertNotIn("Mango Company", entity_item.sparql)
        self.assertIn("MAX(?canonicalMatch)", entity_item.sparql)
        self.assertIn("SUM(?edgeWeight)", entity_item.sparql)

    def test_parse_turtle_reads_labels_roots_and_triples(self):
        labels, roots, triples = parse_turtle(SAMPLE_RDF)

        self.assertEqual(labels["wd:Q1"], Label("Mango", "en"))
        self.assertEqual(labels["wd:Q2"], Label("fruit", "en"))
        self.assertEqual(roots, {"wd:Q1"})
        self.assertEqual(triples, [Triple("wd:Q1", "kg:is", "wd:Q2")])

    def test_build_graph_question_formats_question_and_sparql(self):
        labels, roots, triples = parse_turtle(SAMPLE_RDF)

        item = graph_traversal.build_graph_traversal_items(labels, roots, triples)[0]

        self.assertIn(
            "Which entities are directly linked to Mango?",
            item.question,
        )
        self.assertIn("SELECT DISTINCT ?answer ?subject ?direction", item.sparql)
        self.assertIn("?predicate ?answerEntity", item.sparql)
        self.assertIn("?answerEntity ?predicate", item.sparql)
        self.assertIn("rdfs:label|skos:prefLabel|skos:altLabel", item.sparql)

    def test_generated_query_returns_expected_answer_from_source_rdf(self):
        labels, roots, triples = parse_turtle(SAMPLE_RDF)
        item = graph_traversal.build_graph_traversal_items(labels, roots, triples)[0]

        self.assertNotIn("<http://www.wikidata.org/entity/Q2>", item.sparql)
        self.assertEqual("wd:Q2", item.answer_id)
        self.assertIn("<http://www.wikidata.org/entity/Q2>", item.id_sparql)
        self.assertIn("VALUES ?answer", item.id_sparql)
        self.assertIn("?subject ?predicate1 ?answer", item.id_sparql)
        self.assertIn("?answer ?predicate1 ?subject", item.id_sparql)
        self.assertTrue(
            query_returns_answer(SAMPLE_RDF, item.sparql, EXPECTED_LABEL_ANSWER)
        )
        self.assertTrue(
            query_returns_answer(SAMPLE_RDF, item.id_sparql, item.answer_id)
        )

    def test_only_id_query_matches_when_answer_label_is_missing(self):
        labels, roots, triples = parse_turtle(SAMPLE_RDF)
        item = graph_traversal.build_graph_traversal_items(labels, roots, triples)[0]
        generated_rdf = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix wd: <http://www.wikidata.org/entity/> .
@prefix kg: <https://example.org/wikidata-description/> .

wd:Q1 rdfs:label "Mango"@en ;
    kg:is wd:Q2 .
"""

        self.assertFalse(
            query_returns_answer(generated_rdf, item.sparql, EXPECTED_LABEL_ANSWER)
        )
        self.assertTrue(
            query_returns_answer(generated_rdf, item.id_sparql, item.answer_id)
        )

    def test_relationship_query_accepts_any_predicate(self):
        labels, roots, triples = parse_turtle(SAMPLE_RDF)
        item = graph_traversal.build_graph_traversal_items(labels, roots, triples)[0]
        generated_rdf = SAMPLE_RDF.replace("kg:is wd:Q2", "kg:has_type wd:Q2")

        self.assertTrue(
            query_returns_answer(generated_rdf, item.sparql, EXPECTED_LABEL_ANSWER)
        )
        self.assertTrue(
            query_returns_answer(generated_rdf, item.id_sparql, item.answer_id)
        )

    def test_main_query_does_not_follow_an_unselected_longer_path(self):
        labels, roots, triples = parse_turtle(SAMPLE_RDF)
        item = graph_traversal.build_graph_traversal_items(labels, roots, triples)[0]
        generated_rdf = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix wd: <http://www.wikidata.org/entity/> .
@prefix kg: <https://example.org/wikidata-description/> .

wd:Q1 rdfs:label "Mango"@en ; kg:step kg:middle-1 .
kg:middle-1 kg:step kg:middle-2 .
kg:middle-2 kg:step kg:another-fruit .
kg:another-fruit rdfs:label "fruit"@en .
"""

        self.assertFalse(
            query_returns_answer(generated_rdf, item.sparql, EXPECTED_LABEL_ANSWER)
        )
        self.assertFalse(query_returns_answer(generated_rdf, item.id_sparql, item.answer_id))

    def test_main_query_returns_candidate_label_that_contains_the_answer(self):
        labels, roots, triples = parse_turtle(SAMPLE_RDF)
        item = graph_traversal.build_graph_traversal_items(labels, roots, triples)[0]
        generated_rdf = SAMPLE_RDF.replace('"fruit"@en', '"fruit food"@en')

        self.assertTrue(
            query_returns_answer(generated_rdf, item.sparql, EXPECTED_LABEL_ANSWER)
        )

    def test_main_query_returns_all_linked_labels(self):
        labels, roots, triples = parse_turtle(SAMPLE_RDF)
        item = graph_traversal.build_graph_traversal_items(labels, roots, triples)[0]
        generated_rdf = SAMPLE_RDF.replace(
            "kg:is wd:Q2 .", "kg:is wd:Q2 ; kg:has_part wd:Q3 ."
        ).replace(
            'wd:Q2 rdfs:label "fruit"@en .',
            'wd:Q2 rdfs:label "fruit"@en .\nwd:Q3 rdfs:label "seed"@en .',
        )

        answers = [
            str(row[0])
            for row in Graph().parse(data=generated_rdf, format="turtle").query(item.sparql)
        ]

        self.assertIn("fruit", answers)
        self.assertIn("seed", answers)

    def test_queries_still_work_when_source_label_differs(self):
        labels, roots, triples = parse_turtle(SAMPLE_RDF)
        entity_item, predicate_item = graph_traversal.build_graph_traversal_items(
            labels, roots, triples
        )
        generated_rdf = SAMPLE_RDF.replace('"Mango"@en', '"Mangifera"@en')

        self.assertTrue(
            query_returns_answer(generated_rdf, entity_item.sparql, EXPECTED_LABEL_ANSWER)
        )
        self.assertTrue(
            query_returns_answer(generated_rdf, predicate_item.sparql, '["is"]')
        )

    def test_queries_use_structural_fallback_when_source_id_is_missing(self):
        labels, roots, triples = parse_turtle(SAMPLE_RDF)
        entity_item, predicate_item = graph_traversal.build_graph_traversal_items(
            labels, roots, triples
        )
        generated_rdf = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix wd: <http://www.wikidata.org/entity/> .
@prefix kg: <https://example.org/wikidata-description/> .

kg:mango rdfs:label "Mangifera"@en ;
    kg:is wd:Q2 ;
    kg:hasPart kg:seed .
wd:Q2 rdfs:label "fruit"@en .
kg:seed rdfs:label "seed"@en .
"""

        self.assertTrue(
            query_returns_answer(generated_rdf, entity_item.sparql, EXPECTED_LABEL_ANSWER)
        )
        self.assertTrue(
            query_returns_answer(generated_rdf, predicate_item.sparql, '["is"]')
        )
        self.assertTrue(
            query_returns_answer(generated_rdf, entity_item.id_sparql, "wd:Q2")
        )

    def test_structural_fallback_rejects_target_on_unrelated_edge(self):
        labels, roots, triples = parse_turtle(SAMPLE_RDF)
        item = graph_traversal.build_graph_traversal_items(labels, roots, triples)[0]
        generated_rdf = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix wd: <http://www.wikidata.org/entity/> .
@prefix kg: <https://example.org/wikidata-description/> .

kg:root kg:is kg:a, kg:b, kg:c .
kg:side kg:is wd:Q2 .
wd:Q2 rdfs:label "fruit"@en .
"""

        self.assertFalse(
            query_returns_answer(generated_rdf, item.sparql, EXPECTED_LABEL_ANSWER)
        )
        self.assertFalse(
            query_returns_answer(generated_rdf, item.id_sparql, item.answer_id)
        )

    def test_canonical_source_wins_over_higher_degree_noise(self):
        labels, roots, triples = parse_turtle(SAMPLE_RDF)
        item = graph_traversal.build_graph_traversal_items(labels, roots, triples)[0]
        generated_rdf = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix wd: <http://www.wikidata.org/entity/> .
@prefix kg: <https://example.org/wikidata-description/> .

wd:Q1 kg:is wd:Q2 .
wd:Q2 rdfs:label "fruit"@en .
kg:noise kg:is kg:a, kg:b, kg:c, kg:d .
kg:a rdfs:label "noise-a"@en .
"""

        answers = [
            str(row[0])
            for row in Graph().parse(data=generated_rdf, format="turtle").query(item.sparql)
        ]
        self.assertIn("fruit", answers)
        self.assertNotIn("noise-a", answers)

    def test_id_query_does_not_find_id_from_an_alternate_labeled_resource(self):
        labels, roots, triples = parse_turtle(SAMPLE_RDF)
        item = graph_traversal.build_graph_traversal_items(labels, roots, triples)[0]
        generated_rdf = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix kg: <https://example.org/wikidata-description/> .

kg:mango rdfs:label "Mango"@en ;
    kg:is kg:FruitFood .
"""

        self.assertTrue(
            query_returns_answer(generated_rdf, item.sparql, EXPECTED_LABEL_ANSWER)
        )
        self.assertFalse(
            query_returns_answer(generated_rdf, item.id_sparql, item.answer_id)
        )

    def test_enrich_csv_writes_one_reference_row_per_question(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.csv"
            output_path = Path(temp_dir) / "output.csv"
            with input_path.open("w", newline="", encoding="utf-8") as csv_file:
                writer = csv.DictWriter(
                    csv_file,
                    fieldnames=["identifier", "description", "rdf", "triples"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "identifier": "Mango",
                        "description": "Mango is fruit.",
                        "rdf": SAMPLE_RDF,
                        "triples": "[]",
                    }
                )

            row_count = enrichment_csv.enrich_csv(input_path, output_path)

            with output_path.open(newline="", encoding="utf-8") as csv_file:
                rows = list(csv.DictReader(csv_file))
            id_output_path = enrichment_csv.default_id_output_path(output_path)
            with id_output_path.open(newline="", encoding="utf-8") as csv_file:
                id_rows = list(csv.DictReader(csv_file))

        self.assertEqual(row_count, 2)
        self.assertEqual(
            [
                enrichment_csv.ENRICH_IDENTIFIER_COLUMN,
                enrichment_csv.DESCRIPTION_IDENTIFIER_COLUMN,
                enrichment_csv.QUESTION_COLUMN,
                enrichment_csv.QUERY_TYPE_COLUMN,
                enrichment_csv.SPARQL_COLUMN,
                enrichment_csv.ANSWER_COLUMN,
            ],
            list(rows[0].keys()),
        )
        self.assertEqual("Mango_01", rows[0]["identifier"])
        self.assertEqual("Mango", rows[0]["description_identifier"])
        self.assertNotIn("rdf", rows[0])
        self.assertNotIn("description", rows[0])
        self.assertNotIn("triples", rows[0])
        self.assertEqual(
            "Which entities are directly linked to Mango?",
            rows[0]["question"],
        )
        self.assertEqual("entity", rows[0]["query_type"])
        self.assertEqual("predicate", rows[1]["query_type"])
        self.assertIn("Which predicates", rows[1]["question"])
        self.assertEqual('["is", "type"]', rows[1]["answer"])
        self.assertIn(
            "SELECT DISTINCT ?answer ?subject ?direction",
            rows[0]["sparql"],
        )
        self.assertEqual('["class", "fruit"]', rows[0]["answer"])
        self.assertNotIn("answer_id", rows[0])
        self.assertNotIn("id_sparql", rows[0])
        self.assertEqual(1, len(id_rows))
        self.assertEqual(
            "is the entity Mango directly linked to fruit?",
            id_rows[0]["question"],
        )
        self.assertEqual("wd:Q2", id_rows[0]["answer_id"])
        self.assertIn("<http://www.wikidata.org/entity/Q2>", id_rows[0]["id_sparql"])

    def test_enrich_csv_raises_when_query_does_not_return_answer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.csv"
            output_path = Path(temp_dir) / "output.csv"
            with input_path.open("w", newline="", encoding="utf-8") as csv_file:
                writer = csv.DictWriter(
                    csv_file,
                    fieldnames=["identifier", "description", "rdf", "triples"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "identifier": "Mango",
                        "description": "Mango is fruit.",
                        "rdf": SAMPLE_RDF,
                        "triples": "[]",
                    }
                )

            with patch.object(enrichment_csv, "query_answer_values", return_value=[]):
                with self.assertRaises(ValueError):
                    enrichment_csv.enrich_csv(input_path, output_path)

    def test_enrich_csv_raises_when_id_query_does_not_return_answer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.csv"
            output_path = Path(temp_dir) / "output.csv"
            with input_path.open("w", newline="", encoding="utf-8") as csv_file:
                writer = csv.DictWriter(
                    csv_file,
                    fieldnames=["identifier", "description", "rdf", "triples"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "identifier": "Mango",
                        "description": "Mango is fruit.",
                        "rdf": SAMPLE_RDF,
                        "triples": "[]",
                    }
                )

            with patch.object(
                enrichment_csv,
                "query_returns_answer",
                return_value=False,
            ):
                with self.assertRaisesRegex(ValueError, "Generated ID SPARQL"):
                    enrichment_csv.enrich_csv(input_path, output_path)


if __name__ == "__main__":
    unittest.main()
