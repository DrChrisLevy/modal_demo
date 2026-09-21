"""Checks for data leakage and confidence metrics; no GPU or API credentials needed."""

import unittest
from dataclasses import replace

from datasets import ClassLabel, Dataset, DatasetDict

from experiments.modernbert.data import (
    DatasetConfig,
    clean_training_rows,
    prepare_classification_dataset,
)
from experiments.modernbert.evaluation import (
    classification_metrics,
    select_threshold,
    selective_metrics,
)


class DataTests(unittest.TestCase):
    def test_training_cleanup_leaves_test_untouched(self):
        train = [
            {"text": "Where is my card?", "label": 0},
            {"text": " WHERE  IS MY CARD? ", "label": 0},
            {"text": "Cancel my transfer", "label": 1},
            {"text": "Refund please", "label": 2},
        ]
        # No test labels are needed to detect overlap.
        test = [{"text": "cancel MY transfer"}]
        cleaned, audit = clean_training_rows(train, test)
        self.assertEqual([row["label"] for row in cleaned], [0, 2])
        self.assertEqual(audit["removed_training_duplicates"], 1)
        self.assertEqual(audit["removed_holdout_text_overlap"], 1)
        self.assertEqual(test, [{"text": "cancel MY transfer"}])

    def test_conflicting_training_labels_fail(self):
        with self.assertRaisesRegex(ValueError, "Conflicting labels"):
            clean_training_rows(
                [{"text": "refund", "label": 0}, {"text": "REFUND", "label": 1}], []
            )


class DatasetConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.config = DatasetConfig(
            name="unused-in-memory-fixture",
            input_column="message",
            label_column="intent",
            train_split="training",
            validation_split="dev",
            test_split="heldout",
        )
        self.raw = DatasetDict(
            {
                split: Dataset.from_dict(
                    {
                        "message": [f"{split} message {i}" for i in range(size)],
                        "intent": [i % 2 for i in range(size)],
                        "unused_metadata": ["must not reach the model"] * size,
                    }
                ).cast_column("intent", ClassLabel(names=["zebra", "ant"]))
                for split, size in (("training", 40), ("dev", 6), ("heldout", 8))
            }
        )

    def test_custom_columns_splits_and_classlabel_order(self):
        ds, labels, audit = prepare_classification_dataset(self.raw, self.config)
        # ClassLabel IDs retain their meaning; alphabetically sorting names would corrupt labels.
        self.assertEqual(labels, ["zebra", "ant"])
        self.assertEqual(ds["train"].column_names, ["text", "label", "example_id"])
        self.assertEqual(ds["train"].features["label"].dtype, "int64")
        self.assertEqual(ds["validation"]["label"], [0, 1, 0, 1, 0, 1])
        self.assertEqual(ds["validation"]["example_id"], [f"dev-{i}" for i in range(6)])
        self.assertIsNone(audit["validation_fraction"])

    def test_string_labels_and_unknown_holdout_class(self):
        raw = DatasetDict(
            {
                split: data.remove_columns("intent").add_column(
                    "intent", ["zebra" if i % 2 == 0 else "ant" for i in range(len(data))]
                )
                for split, data in self.raw.items()
            }
        )
        ds, labels, _ = prepare_classification_dataset(raw, self.config)
        self.assertEqual(labels, ["ant", "zebra"])
        self.assertEqual(ds["train"]["label"][:4], [1, 0, 1, 0])
        configured = replace(self.config, id2label={0: "zebra", 1: "ant"})
        ds, labels, _ = prepare_classification_dataset(raw, configured)
        self.assertEqual(labels, ["zebra", "ant"])
        self.assertEqual(ds["train"]["label"][:4], [0, 1, 0, 1])
        raw["heldout"] = (
            raw["heldout"].remove_columns("intent").add_column("intent", ["never-in-training"] * 8)
        )
        with self.assertRaisesRegex(ValueError, "unknown class"):
            prepare_classification_dataset(raw, self.config)

    def test_generated_validation_is_fixed_before_few_shot_selection(self):
        config = replace(self.config, validation_split=None)
        full, labels, _ = prepare_classification_dataset(self.raw, config, validation_fraction=0.2)
        few, _, _ = prepare_classification_dataset(
            self.raw, config, validation_fraction=0.2, train_per_class=3
        )
        self.assertEqual(len(few["train"]), 3 * len(labels))
        for split in ("validation", "test"):
            self.assertEqual(list(full[split]["example_id"]), list(few[split]["example_id"]))
        self.assertFalse(set(full["train"]["example_id"]) & set(full["validation"]["example_id"]))

    def test_float_multilabel_missing_and_out_of_range_targets_fail(self):
        for invalid in (0.0, [0, 1], None, -1, 2):
            with self.subTest(target=invalid):
                raw = DatasetDict(self.raw)
                raw["heldout"] = (
                    raw["heldout"].remove_columns("intent").add_column("intent", [invalid] * 8)
                )
                with self.assertRaisesRegex(ValueError, "target must|outside"):
                    prepare_classification_dataset(raw, self.config)

    def test_inconsistent_classlabel_order_fails(self):
        raw = DatasetDict(self.raw)
        raw["heldout"] = raw["heldout"].cast_column("intent", ClassLabel(names=["ant", "zebra"]))
        with self.assertRaisesRegex(ValueError, "ClassLabel ordering differs"):
            prepare_classification_dataset(raw, self.config)

    def test_missing_columns_and_reused_splits_fail_early(self):
        with self.assertRaisesRegex(ValueError, "missing configured columns"):
            prepare_classification_dataset(self.raw, replace(self.config, label_column="wrong"))
        with self.assertRaisesRegex(ValueError, "distinct source splits"):
            prepare_classification_dataset(self.raw, replace(self.config, test_split="training"))


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
