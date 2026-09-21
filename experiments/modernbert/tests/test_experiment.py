"""Checks for data leakage and confidence metrics; no GPU or API credentials needed."""

import unittest

from experiments.modernbert.data import clean_training_rows
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
        self.assertEqual(audit["removed_test_text_overlap"], 1)
        self.assertEqual(test, [{"text": "cancel MY transfer"}])

    def test_conflicting_training_labels_fail(self):
        with self.assertRaisesRegex(ValueError, "Conflicting labels"):
            clean_training_rows(
                [{"text": "refund", "label": 0}, {"text": "REFUND", "label": 1}], []
            )


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
