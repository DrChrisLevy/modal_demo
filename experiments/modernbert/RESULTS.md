# First Banking77 baseline — September 21, 2026

[Modal run](https://modal.com/apps/drchrislevy/main/ap-kIlv8UAlItQyO2Xv7UT9l5) ·
[Raw report](reports/banking77-base-seed42.json) · code commit `493065f`

ModernBERT-base, all encoder weights trained, seed 42, two epochs, learning rate
5e-5, batch size 32, maximum 128 tokens, bf16, fused AdamW, PyTorch SDPA, one NVIDIA L4.
The learning rate follows the Trainer's default linear schedule without warmup.
The second epoch had the best validation macro-F1 and supplied the evaluated weights.

| Metric | Validation | Official test |
| --- | ---: | ---: |
| Examples | 1,000 | 3,080 |
| Accuracy | 91.50% | **92.34%** |
| Macro-F1 | 91.99% | **92.31%** |
| NLL | 0.3362 | 0.2728 |
| Multiclass Brier, summed across classes | 0.1352 | 0.1142 |
| ECE, 15 equal-width bins | 0.0239 | 0.0071 |

Training took **76.43 seconds**, excluding container startup, dependency image build,
initial dataset/model loading and final evaluation. Peak allocated GPU memory was
3.76 GiB. Final test evaluation processed about 936 examples/second at batch size 32;
this includes Trainer evaluation overhead and is not single-request latency.

## Abstention

The threshold was selected exclusively on validation for maximum coverage at
least 95% empirical accuracy: accept if maximum class probability is at least
`0.5721871733736861`.

| Measure | Validation | Test, with the same threshold |
| --- | ---: | ---: |
| Accepted examples | 928 / 1,000 | 2,885 / 3,080 |
| Coverage | 92.80% | **93.67%** |
| Accuracy among accepted examples | 95.04% | **95.60%** |

The target is an empirical validation criterion, not a guaranteed production error
rate. No probability rounding or test-set threshold fitting was used.

## Protocol and artifacts

Training used 8,992 rows after removing four normalized training duplicates,
seven normalized overlaps with test, and reserving 1,000 validation rows. All 77
classes and all 3,080 official test rows were retained. The normalized overlap check
uses case folding and collapsed whitespace, without consulting test labels.

This is a **single-seed initial baseline**, with no hyperparameter search. Jev has
not been evaluated here yet. Results from another person's Jev benchmark are not
paired comparisons with these predictions, particularly when splits or label
descriptions differ.

The successful smoke run exercised training, evaluation, checkpoint loading and
artifact persistence. Seven local tests passed, and a data check confirmed that the
full and 10-per-class configurations have identical validation/test IDs and no
normalized text overlap across partitions. Only the full baseline was trained;
the few-shot commands are prepared for subsequent experiments.

Complete run directory on Modal Volume `modernbert-banking77`:

```text
runs/banking77-base-full-s42-20260921T170045Z-4cd381/
```

It contains the selected model, both epoch checkpoints, validation/test prediction
arrays, per-class reports, run manifest and training logs. The local gitignored
`results/` directory contains downloaded reports and test predictions. The committed
JSON report preserves the exact config, major package versions, revisions, source
hashes and label ordering; the complete manifest also records each split's example IDs.

For the next Jev experiment, freeze this split and label order, use the same 3,080
test examples, and select prompts/thresholds on validation. Report Jev as zero-shot
and ModernBERT as supervised, and compare paired predictions rather than unrelated
leaderboard scores.
