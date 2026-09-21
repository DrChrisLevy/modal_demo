"""Checks for dataset preparation and confidence metrics; no GPU required."""

import unittest
from unittest.mock import patch

from datasets import ClassLabel, Dataset, DatasetDict, Value

from experiments.modernbert.evaluation import (
    classification_metrics,
    select_threshold,
    selective_metrics,
)
from experiments.modernbert.trainer import DEFAULTS, load_data


class DataTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "load": {"path": "in-memory-fixture"},
            "input_column": "message",
            "label_column": "intent",
            "splits": {"train": "training", "validation": "dev", "test": "heldout"},
            "id2label": None,
            "clean_training": False,
        }
        self.raw = DatasetDict(
            {
                split: Dataset.from_dict(
                    {
                        "message": [f"{split} message {i}" for i in range(size)],
                        "intent": [i % 2 for i in range(size)],
                        "metadata": ["not a model input"] * size,
                    }
                ).cast_column("intent", ClassLabel(names=["zebra", "ant"]))
                for split, size in (("training", 40), ("dev", 6), ("heldout", 8))
            }
        )

    def load(self, **overrides):
        with patch("datasets.load_dataset", return_value=self.raw):
            return load_data(self.settings, {**DEFAULTS, **overrides})

    def test_custom_columns_preserve_class_order_and_supplied_splits(self):
        ds, labels, _ = self.load()
        self.assertEqual(labels, ["zebra", "ant"])
        self.assertEqual(ds["train"].column_names, ["text", "label", "example_id"])
        self.assertEqual(ds["train"].features["label"].dtype, "int64")
        self.assertEqual(list(ds["validation"]["example_id"]), [f"dev-{i}" for i in range(6)])
        self.assertEqual(list(ds["validation"]["label"]), [0, 1, 0, 1, 0, 1])

    def test_strings_use_configured_class_order(self):
        for split, data in self.raw.items():
            self.raw[split] = data.remove_columns("intent").add_column(
                "intent", ["zebra" if i % 2 == 0 else "ant" for i in range(len(data))]
            )
        for storage in ("string", "large_string"):
            with self.subTest(storage=storage):
                self.raw = DatasetDict(
                    {
                        split: data.cast_column("intent", Value(storage))
                        for split, data in self.raw.items()
                    }
                )
                self.settings["id2label"] = {0: "zebra", 1: "ant"}
                ds, labels, _ = self.load()
                self.assertEqual(labels, ["zebra", "ant"])
                self.assertEqual(list(ds["train"]["label"])[:4], [0, 1, 0, 1])
                self.settings["id2label"] = None
                ds, labels, _ = self.load()
                self.assertEqual(labels, ["ant", "zebra"])
                self.assertEqual(list(ds["train"]["label"])[:4], [1, 0, 1, 0])

    def test_cleanup_preserves_holdouts_and_rejects_conflicting_duplicates(self):
        self.settings.update(clean_training=True, id2label={0: "zebra", 1: "ant"})
        self.raw["training"] = Dataset.from_dict(
            {
                "message": ["Alpha", " ALPHA ", "Beta", "dev message 0", "heldout message 0"],
                "intent": [0, 0, 1, 0, 0],
            }
        )
        ds, _, audit = self.load()
        self.assertEqual(list(ds["train"]["example_id"]), ["training-0", "training-2"])
        self.assertEqual(audit["removed_training_rows"], 3)
        self.assertEqual(list(ds["test"]["text"]), list(self.raw["heldout"]["message"]))
        self.raw["training"] = (
            self.raw["training"].remove_columns("intent").add_column("intent", [0, 1, 1, 0, 0])
        )
        with self.assertRaisesRegex(ValueError, "Conflicting training labels"):
            self.load()

    def test_few_shot_selection_keeps_validation_and_test_fixed(self):
        self.settings["splits"]["validation"] = None
        full, _, _ = self.load(validation_fraction=0.2)
        few, _, _ = self.load(validation_fraction=0.2, train_per_class=3)
        self.assertEqual(len(few["train"]), 6)
        for split in ("validation", "test"):
            self.assertEqual(list(full[split]["example_id"]), list(few[split]["example_id"]))
        self.assertFalse(set(full["train"]["example_id"]) & set(full["validation"]["example_id"]))


class MetricTests(unittest.TestCase):
    def test_perfect_predictions(self):
        metrics = classification_metrics([[1.0, 0.0], [0.0, 1.0]], [0, 1])
        self.assertEqual(metrics["accuracy"], 1.0)
        self.assertEqual(metrics["f1_macro"], 1.0)
        self.assertEqual(metrics["brier"], 0.0)
        self.assertEqual(metrics["ece_15_bins"], 0.0)
        self.assertAlmostEqual(metrics["nll"], 0.0)

    def test_confident_mistakes_are_penalized(self):
        metrics = classification_metrics([[0.99, 0.01], [0.01, 0.99]], [1, 0])
        self.assertEqual(metrics["accuracy"], 0.0)
        self.assertAlmostEqual(metrics["brier"], 1.9602)
        self.assertAlmostEqual(metrics["ece_15_bins"], 0.99)
        self.assertGreater(metrics["nll"], 4.6)

    def test_threshold_cannot_split_confidence_ties(self):
        probabilities = [[0.9, 0.1], [0.1, 0.9]]
        self.assertIsNone(select_threshold(probabilities, [0, 0], 1.0))
        rejected = selective_metrics(probabilities, [0, 0], None)
        self.assertEqual(rejected["coverage"], 0.0)
        self.assertIsNone(rejected["accuracy"])

    def test_threshold_maximizes_coverage_even_if_accuracy_is_nonmonotonic(self):
        probabilities = [[0.99, 0.01], [0.9, 0.1], [0.6, 0.4]]
        threshold = select_threshold(probabilities, [0, 1, 0], 2 / 3)
        self.assertEqual(threshold, 0.6)
        self.assertEqual(selective_metrics(probabilities, [0, 1, 0], threshold)["coverage"], 1.0)

    def test_validation_threshold_does_not_claim_test_accuracy_guarantee(self):
        threshold = select_threshold([[0.9, 0.1], [0.6, 0.4]], [0, 1], 1.0)
        test = selective_metrics([[0.95, 0.05], [0.7, 0.3]], [1, 0], threshold)
        self.assertEqual(threshold, 0.9)
        self.assertEqual(test["coverage"], 0.5)
        self.assertEqual(test["accuracy"], 0.0)


if __name__ == "__main__":
    unittest.main()
