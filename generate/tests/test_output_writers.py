import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from generate_pipeline import cli
from generate_pipeline.io import output_writers
from generate_pipeline.models import GeneratedText


class OutputWriterTests(unittest.TestCase):
    def test_normalize_names_trims_and_rejects_invalid_input(self):
        self.assertEqual(["car", "automobile"], cli.normalize_names([" car ", "automobile "]))

        with self.assertRaises(ValueError):
            cli.normalize_names([])
        with self.assertRaises(ValueError):
            cli.normalize_names(["car", "automobile", "vehicle"])
        with self.assertRaises(ValueError):
            cli.normalize_names([" "])

    def test_select_unique_phrases_excludes_seen_and_duplicate_text(self):
        phrases = ["Already used", "Fresh phrase", "fresh phrase.", "Another phrase"]

        selected = cli.select_unique_phrases(
            phrases,
            {cli.phrase_key("Already used")},
        )

        self.assertEqual(["Fresh phrase", "Another phrase"], selected)

    def test_combine_generated_texts_merges_each_representation(self):
        first = GeneratedText("First.", "rdf-one", [("A", "is", "B")], 1)
        second = GeneratedText("Second.", "rdf-two", [("C", "is", "D")], 2)

        with patch.object(cli, "combine_rdf_graphs", return_value="combined") as combine:
            result = cli.combine_generated_texts([first, second])

        combine.assert_called_once_with(["rdf-one", "rdf-two"])
        self.assertEqual("First. Second.", result.description)
        self.assertEqual("combined", result.rdf)
        self.assertEqual([("A", "is", "B"), ("C", "is", "D")], result.triples)
        self.assertEqual(3, result.related_entity_count)

    def test_two_names_use_only_the_first_match_of_each(self):
        with patch.object(
            cli,
            "find_entity_ids_by_name",
            side_effect=[["Q1"], ["Q2"]],
        ) as lookup:
            result = cli.find_candidate_ids(["car", "automobile"], "en")

        self.assertEqual(["Q1", "Q2"], result)
        self.assertEqual([("car", "en"), ("automobile", "en")], [
            call.args for call in lookup.call_args_list
        ])
        self.assertTrue(all(call.kwargs == {"limit": 1} for call in lookup.call_args_list))
        self.assertEqual("Car-Automobile", cli.entity_identifier(["car", "automobile"]))

    def test_csv_has_identifier_matches_case_insensitively(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "out.csv"
            output_writers.append_csv(
                str(csv_path),
                "Mango",
                "A description.",
                "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
                [],
            )

            self.assertTrue(output_writers.csv_has_identifier(str(csv_path), " mango "))
            self.assertFalse(output_writers.csv_has_identifier(str(csv_path), "Jaguar"))

    def test_csv_has_identifier_returns_false_for_missing_csv(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "missing.csv"

            self.assertFalse(output_writers.csv_has_identifier(str(csv_path), "Mango"))

    def test_cli_skips_existing_identifier_before_wikidata_lookup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "out.csv"
            output_writers.append_csv(
                str(csv_path),
                "Mango_01",
                "A description.",
                "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
                [],
            )

            with (
                patch("sys.argv", ["main.py", "mango", "--csv", str(csv_path)]),
                patch.object(cli, "find_entity_ids_by_name") as lookup,
            ):
                exit_code = cli.main()

            self.assertEqual(0, exit_code)
            lookup.assert_not_called()

    def test_cli_writes_one_rdf_row_per_text(self):
        entities = {
            "Q1": {"id": "Q1", "labels": {"en": {"value": "First"}}, "sitelinks": {"enwiki": {"title": "First"}}},
            "Q2": {"id": "Q2", "labels": {"en": {"value": "Second"}}, "sitelinks": {"enwiki": {"title": "Second"}}},
        }
        phrases = {
            "First": ["First phrase one", "First phrase two"],
            "Second": ["Second phrase one", "Second phrase two"],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "out.csv"
            graph_csv_path = Path(temp_dir) / "graphs.csv"
            with (
                patch("sys.argv", ["main.py", "thing", "--csv", str(csv_path), "--graph-csv", str(graph_csv_path)]),
                patch.object(cli, "find_candidate_ids", return_value=["Q1", "Q2"]),
                patch.object(cli, "fetch_entity", side_effect=lambda entity_id, _lang: entities[entity_id]),
                patch.object(cli, "fetch_wikipedia_phrases", side_effect=lambda title, _lang, limit: phrases[title][:limit]),
                patch.object(
                    cli,
                    "extract_relations",
                    side_effect=[
                        [("Q1", "is", "Q11")],
                        [("Q2", "is", "Q22")],
                    ],
                ),
                patch.object(cli, "fetch_labels", side_effect=[{"Q11": "Alpha"}, {"Q22": "Beta"}]),
            ):
                exit_code = cli.main()

            with csv_path.open(newline="", encoding="utf-8") as csv_file:
                rows = list(csv.DictReader(csv_file))
            with graph_csv_path.open(newline="", encoding="utf-8") as csv_file:
                graph_rows = list(csv.DictReader(csv_file))

        self.assertEqual(0, exit_code)
        self.assertEqual(["Thing_01", "Thing_02"], [row["identifier"] for row in rows])
        self.assertEqual("First phrase one. First phrase two.", rows[0]["description"])
        self.assertEqual("Second phrase one. Second phrase two.", rows[1]["description"])
        self.assertIn("wd:Q1", rows[0]["rdf"])
        self.assertNotIn("wd:Q2", rows[0]["rdf"])
        self.assertIn("wd:Q2", rows[1]["rdf"])
        self.assertNotIn("wd:Q1", rows[1]["rdf"])
        self.assertEqual(1, len(graph_rows))
        self.assertEqual("Thing", graph_rows[0]["identifier"])
        self.assertEqual(
            "First phrase one. First phrase two. Second phrase one. Second phrase two.",
            graph_rows[0]["description"],
        )
        self.assertIn("wd:Q1", graph_rows[0]["rdf"])
        self.assertIn("wd:Q2", graph_rows[0]["rdf"])
        self.assertEqual(
            [["First", "is", "Alpha"], ["Second", "is", "Beta"]],
            json.loads(graph_rows[0]["triples"]),
        )

    def test_triples_json_dedupes_and_prunes_redundant_objects(self):
        triples = [
            ("Mango", "is", "fruit"),
            (" Mango ", " is ", " fruit "),
            ("Mango", "is", "tropical fruit"),
        ]

        encoded = output_writers.triples_json(triples)

        self.assertEqual(json.loads(encoded), [["Mango", "is", "fruit"]])

    def test_build_rdf_escapes_labels_and_adds_relations(self):
        entity = {
            "id": "Q1",
            "labels": {"en": {"value": 'Root "Entity"'}},
        }

        rdf = output_writers.build_rdf(
            entity=entity,
            lang="en",
            labels={"Q2": "Leaf"},
            related_ids={"Q2"},
            relations=[("Q1", "knownFor", "Q2")],
        )

        self.assertIn('rdfs:label "Root \\"Entity\\""@en', rdf)
        self.assertIn("kg:knownFor wd:Q2", rdf)
        self.assertIn('wd:Q2 rdfs:label "Leaf"@en .', rdf)
        self.assertNotIn(" a wd:", rdf)

    def test_append_csv_writes_expected_columns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "out.csv"

            output_writers.append_csv(
                str(csv_path),
                "Mango",
                "A description.",
                "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
                [("A", "is", "B")],
            )

            with csv_path.open(newline="", encoding="utf-8") as csv_file:
                rows = list(csv.DictReader(csv_file))

        self.assertEqual(
            ["identifier", "description", "rdf", "triples"],
            list(rows[0].keys()),
        )
        self.assertEqual("Mango", rows[0]["identifier"])
        self.assertEqual("A description.", rows[0]["description"])
        self.assertEqual([["A", "is", "B"]], json.loads(rows[0]["triples"]))


if __name__ == "__main__":
    unittest.main()
