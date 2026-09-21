# ModernBERT on Banking77

Fine-tune the encoder on Modal, then evaluate the validation-selected checkpoint on
all 3,080 official test examples. This is a supervised specialist baseline for a
later comparison with zero-shot Jev. No Jev scores are inferred from other people's runs.

## Original script and migration

The first experiment commit, `ab60b5c`, imports `trainer.py` **unchanged** from
[Chris's blog source](https://github.com/DrChrisLevy/DrChrisLevy.github.io/blob/efa64bc0ebe8f40b566d25627b748a705016b9bf/posts/modern_bert/trainer.py).
Its Git blob is `626681c391adc88bf3b708dbf23c0db64dffdc69`; the upstream file was last
changed December 28, 2024. The accompanying
[notebook](https://drchrislevy.com/blog/blog_post?fpath=posts%2Fmodern_bert%2Fmodern_bert.ipynb)
explains the original emotion-classification experiment.

```bash
git show ab60b5c:experiments/modernbert/trainer.py
git diff ab60b5c -- experiments/modernbert/trainer.py
```

| Original | Current experiment | Reason |
| --- | --- | --- |
| `@build()` stacked with `@enter()` | `@modal.enter()` for GPU setup; data loaded during the run | Modal removed the build hook; mounted Volume data belongs at runtime. |
| `container_idle_timeout` | `scaledown_window` | Modal 1.0 API rename. |
| Unpinned Transformers Git main and ML packages | Pinned stable packages and model revisions | Repeatable image and checkpoint selection. |
| CUDA-devel image + compile `flash-attn` | Debian Python image + PyTorch CUDA wheels + explicit SDPA | ModernBERT supports native SDPA; avoids a CUDA extension build. This is an implementation choice. |
| `transformers.utils.move_cache()` | Removed | Obsolete cache migration; `HF_HOME` points at the persistent Volume. |
| `Trainer(tokenizer=...)` | `Trainer(processing_class=...)` | Current Transformers API. |
| W&B key required at import and baked into image command | JSON reports without W&B | Works with only Modal credentials; no API key in image layers. |
| Emotion's supplied validation split | Stratified validation from Banking77 training | Banking77 only ships train/test. |
| HF Python dataset loader | Original CSVs at a pinned upstream commit | Current Datasets no longer executes dataset loading scripts. |
| Padding in dataset mapping | Dynamic padding in `DataCollatorWithPadding` | Padding now follows actual training batches. |
| Select last checkpoint for evaluation | Save/evaluate weights selected by validation macro-F1 | The last checkpoint need not be the best. |
| Probabilities rounded to two decimals | Full-precision probabilities and logits | Rounding breaks calibration and threshold analysis. |
| Destructive reuse of run directory | Unique run directory and explicit Volume commit | Preserve prior results and failed-run artifacts. |

Primary docs: [Modal index](https://modal.com/llms.txt),
[Modal 1.0 migration](https://modal.com/docs/guide/modal-1-0-migration),
[Volumes](https://modal.com/docs/guide/volumes),
[HF Trainer](https://huggingface.co/docs/transformers/v5.17.0/en/main_classes/trainer),
[ModernBERT](https://huggingface.co/docs/transformers/v5.17.0/en/model_doc/modernbert).

## Run

Use the existing repository `uv` environment. PyTorch and Transformers install only
inside Modal; optional local checks use NumPy, scikit-learn and Datasets. No deployed
web service or Docker VM is needed.

```bash
# Five optimizer steps on small slices; NOT a benchmark result.
uv run modal run -m experiments.modernbert.trainer --smoke

# Full baseline: ModernBERT-base, two epochs, seed 42, one L4 GPU.
uv run modal run -m experiments.modernbert.trainer

# Learning curve: select training examples per class AFTER creating validation.
uv run modal run -m experiments.modernbert.trainer --train-per-class 10
uv run modal run -m experiments.modernbert.trainer --train-per-class 25
uv run modal run -m experiments.modernbert.trainer --train-per-class 50

# Other configurations; each invocation creates a separate run.
uv run modal run -m experiments.modernbert.trainer --model-size large --gpu A100-40GB
uv run modal run -m experiments.modernbert.trainer --epochs 3 --seed 43
```

The original batch size (32), learning rate (5e-5), two epochs, bf16, and fused AdamW
are retained. Maximum length is 128 rather than 512 because these are short queries;
override it with `--max-length`. All encoder weights are trained. There is no LoRA or
frozen-encoder shortcut. The remote method has a 30-minute timeout.

## Data and evaluation protocol

- Source: [PolyAI Banking77](https://github.com/PolyAI-LDN/task-specific-datasets/tree/9d081458ff52e53cf7e848f414e6e9344e4e6696/banking_data),
  77 labels, 10,003 original training rows and 3,080 test rows (CC BY 4.0).
- Normalize text with case folding and whitespace collapsing for duplicate checks.
  Remove repeated training texts and training texts that also occur in test. Test
  **labels are not used** for this cleaning; the official test stays intact.
  This removes four repeated training rows and seven test-text overlaps, leaving
  8,992 training and 1,000 validation examples at the default split.
- Reserve 10% of cleaned training data for stratified validation using the run seed.
  Few-shot subsets use the remaining training partition and do not change validation/test.
  This slightly changes the training protocol from an uncleaned Banking77 run.
- Select the best epoch by validation macro-F1, then evaluate test once. Report
  accuracy, macro/micro-F1, multiclass Brier (sum across classes), NLL, and 15-bin ECE.
- Select the confidence threshold for maximum validation coverage at 95% empirical
  accuracy. Apply that exact threshold on test and report both coverage and accuracy.
  This is not a statistical guarantee of 95% accuracy; `null` means no qualifying threshold.
- Report batched evaluation throughput separately from single-request API latency.
  Do not use that throughput to claim a like-for-like latency win against Jev.
- One seed is an initial baseline. Use multiple seeds and a validation-only tuning
  protocol before making a model superiority claim. Public pretraining overlap is unknown.

## Artifacts

The dedicated Modal Volume is `modernbert-banking77`; each run lives under `runs/<run>`.
The entrypoint downloads `summary.json`, `manifest.json`, and `training_log.json` to
`experiments/modernbert/results/<run>/` (gitignored). The manifest records the config,
dependency versions, GPU, dataset/model revisions, source hashes, label order and
the exact example IDs in every split.

The Volume additionally contains `best_model/`, training checkpoints,
`validation_predictions.npz`, `test_predictions.npz`, and per-class reports. Prediction
arrays contain `logits`, `probabilities`, `labels`, and `example_ids`, with columns in
the manifest's label order. Keep the same test IDs and label definitions for Jev.

```bash
uv run modal volume ls modernbert-banking77 runs
uv run modal volume get modernbert-banking77 runs/<run> ./artifacts/<run>
```

## Local checks

```bash
uv run ruff check experiments
uv run ruff format --check experiments
uv run --with numpy==2.5.3 --with scikit-learn==1.9.1 \
  python -m unittest discover -s experiments/modernbert/tests -v
```

The tests check leakage cleanup, calibration arithmetic, confidence ties and
validation/test separation. The Modal smoke run checks the actual GPU training,
checkpoint reload, evaluation, persistence and local report-download path.
