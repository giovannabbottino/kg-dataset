import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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


class EnrichTests(unittest.TestCase):
    def test_main_query_preserves_hyphens_in_expected_labels(self):
        rdf = SAMPLE_RDF.replace('"fruit"@en', '"singer-songwriter"@en')
        labels, roots, triples = parse_turtle(rdf)
        item = graph_traversal.build_graph_traversal_items(labels, roots, triples)[0]

        self.assertIn("'singer-songwriter'", item["sparql"])
        self.assertTrue(query_returns_answer(rdf, item["sparql"], item["answer"]))

    def test_parse_turtle_reads_labels_roots_and_triples(self):
        labels, roots, triples = parse_turtle(SAMPLE_RDF)

        self.assertEqual(labels["wd:Q1"], Label("Mango", "en"))
        self.assertEqual(labels["wd:Q2"], Label("fruit", "en"))
        self.assertEqual(roots, {"wd:Q1"})
        self.assertEqual(triples, [Triple("wd:Q1", "kg:is", "wd:Q2")])

    def test_build_graph_traversal_formats_question_sparql_and_answer(self):
        labels, roots, triples = parse_turtle(SAMPLE_RDF)

        result = graph_traversal.build_graph_traversal(labels, roots, triples)

        self.assertIn(
            "What answer is reached by this graph path: Mango --kg:is--> fruit?",
            result,
        )
        self.assertIn("SELECT ?answer WHERE", result)
        self.assertIn("?subject rdfs:label ?subjectLabel", result)
        self.assertIn("?answerEntity rdfs:label ?answerLabel", result)
        self.assertIn("'answer': 'fruit'", result)

    def test_generated_query_returns_expected_answer_from_source_rdf(self):
        labels, roots, triples = parse_turtle(SAMPLE_RDF)
        item = graph_traversal.build_graph_traversal_items(labels, roots, triples)[0]

        self.assertNotIn("<http://www.wikidata.org/entity/Q2>", item["sparql"])
        self.assertEqual("wd:Q2", item["answer_id"])
        self.assertIn("<http://www.wikidata.org/entity/Q2>", item["id_sparql"])
        self.assertIn("?predicate1 ?answer", item["id_sparql"])
        self.assertNotIn("BIND", item["id_sparql"])
        self.assertTrue(
            query_returns_answer(SAMPLE_RDF, item["sparql"], item["answer"])
        )
        self.assertTrue(
            query_returns_answer(SAMPLE_RDF, item["id_sparql"], item["answer_id"])
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
            query_returns_answer(generated_rdf, item["sparql"], item["answer"])
        )
        self.assertTrue(
            query_returns_answer(generated_rdf, item["id_sparql"], item["answer_id"])
        )

    def test_both_queries_allow_a_different_predicate(self):
        labels, roots, triples = parse_turtle(SAMPLE_RDF)
        item = graph_traversal.build_graph_traversal_items(labels, roots, triples)[0]
        generated_rdf = SAMPLE_RDF.replace("kg:is wd:Q2", "kg:has_type wd:Q2")

        self.assertTrue(
            query_returns_answer(generated_rdf, item["sparql"], item["answer"])
        )
        self.assertTrue(
            query_returns_answer(generated_rdf, item["id_sparql"], item["answer_id"])
        )

    def test_main_query_requires_the_expected_answer_label(self):
        labels, roots, triples = parse_turtle(SAMPLE_RDF)
        item = graph_traversal.build_graph_traversal_items(labels, roots, triples)[0]
        generated_rdf = SAMPLE_RDF.replace('"fruit"@en', '"fruit food"@en')

        self.assertFalse(
            query_returns_answer(generated_rdf, item["sparql"], item["answer"])
        )

    def test_id_query_does_not_find_id_from_an_alternate_labeled_resource(self):
        labels, roots, triples = parse_turtle(SAMPLE_RDF)
        item = graph_traversal.build_graph_traversal_items(labels, roots, triples)[0]
        generated_rdf = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix kg: <https://example.org/wikidata-description/> .

kg:mango rdfs:label "Mango"@en ;
    kg:is kg:FruitFood .
"""

        self.assertFalse(
            query_returns_answer(generated_rdf, item["sparql"], item["answer"])
        )
        self.assertFalse(
            query_returns_answer(generated_rdf, item["id_sparql"], item["answer_id"])
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

        self.assertEqual(row_count, 1)
        self.assertEqual(
            [
                enrichment_csv.ENRICH_IDENTIFIER_COLUMN,
                enrichment_csv.DESCRIPTION_IDENTIFIER_COLUMN,
                enrichment_csv.QUESTION_COLUMN,
                enrichment_csv.SPARQL_COLUMN,
                enrichment_csv.ANSWER_COLUMN,
                enrichment_csv.ANSWER_ID_COLUMN,
                enrichment_csv.ID_SPARQL_COLUMN,
            ],
            list(rows[0].keys()),
        )
        self.assertEqual("Mango_01", rows[0]["identifier"])
        self.assertEqual("Mango", rows[0]["description_identifier"])
        self.assertNotIn("rdf", rows[0])
        self.assertNotIn("description", rows[0])
        self.assertNotIn("triples", rows[0])
        self.assertEqual(
            "What answer is reached by this graph path: Mango --kg:is--> fruit?",
            rows[0]["question"],
        )
        self.assertIn("SELECT ?answer WHERE", rows[0]["sparql"])
        self.assertEqual("fruit", rows[0]["answer"])
        self.assertEqual("wd:Q2", rows[0]["answer_id"])
        self.assertIn("<http://www.wikidata.org/entity/Q2>", rows[0]["id_sparql"])

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

            with patch.object(enrichment_csv, "query_returns_answer", return_value=False):
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

            def only_main_query_passes(_rdf, sparql, _answer):
                return sparql.startswith("PREFIX rdfs:")

            with patch.object(
                enrichment_csv,
                "query_returns_answer",
                side_effect=only_main_query_passes,
            ):
                with self.assertRaisesRegex(ValueError, "Generated ID SPARQL"):
                    enrichment_csv.enrich_csv(input_path, output_path)


if __name__ == "__main__":
    unittest.main()
