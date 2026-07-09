import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from generate_pipeline.io import output_writers


class OutputWriterTests(unittest.TestCase):
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
            type_ids_by_entity={"Q1": {"Q5"}, "Q2": {"Q10"}},
            class_labels={"Q5": "human", "Q10": "class"},
        )

        self.assertIn('rdfs:label "Root \\"Entity\\""@en', rdf)
        self.assertIn("kg:knownFor wd:Q2", rdf)
        self.assertIn('wd:Q2 a wd:Q10 ;\n    rdfs:label "Leaf"@en .', rdf)

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
