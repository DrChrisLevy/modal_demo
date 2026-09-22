"""Fine-tune ModernBERT on Modal; adapted from Chris Levy's December 2024 trainer.

Original blog post:
https://drchrislevy.com/blog/blog_post?fpath=posts%2Fmodern_bert%2Fmodern_bert.ipynb

Edit the configuration below, then run:
    uv run modal run slides/trainer.py
    uv run modal run slides/trainer.py --smoke
"""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import modal

# ---------------------------------- SETUP BEGIN ----------------------------------#
DATASET = {
    "path": "csv",
    "data_files": {
        "train": (
            "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/"
            "9d081458ff52e53cf7e848f414e6e9344e4e6696/banking_data/train.csv"
        ),
        "test": (
            "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/"
            "9d081458ff52e53cf7e848f414e6e9344e4e6696/banking_data/test.csv"
        ),
    },
}
# Example: DATASET = {"path": "dair-ai/emotion", "name": "split"}
SPLITS = {"train": "train", "validation": None, "test": "test"}
INPUT_COLUMN = "text"
LABEL_COLUMN = "category"
ID2LABEL = None  # Use dataset ClassLabel names or infer sorted label names from training.
VALIDATION_FRACTION = 0.1  # Used only when no validation split is supplied.

CHECKPOINT = "answerdotai/ModernBERT-base"
MODEL_REVISION = "8949b909ec900327062f0ebf497f51aef5e6f0c8"  # None uses the latest revision.
MAX_LENGTH = 512
SEED = 42
BATCH_SIZE = 32
NUM_TRAIN_EPOCHS = 2
LEARNING_RATE = 5e-5
CONFIDENCE_THRESHOLDS = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
SMOKE_ROWS = 128
SMOKE_STEPS = 5

RUN_NAME = "banking77-modernbert"
VOLUME_NAME = "modern_bert_runs"
DATA_ROOT = Path("/data")
GPU = "L4"
CPU = 4
MEMORY_MB = 16384
TIMEOUT = 60 * 60 * 10
# ---------------------------------- SETUP END ----------------------------------#

app = modal.App("modernbert-classifier")
image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "torch==2.14.0",
        "transformers==5.17.0",
        "datasets==5.0.1",
        "accelerate==1.15.0",
        "scikit-learn==1.9.1",
        "numpy==2.5.3",
    )
    .env({"HF_HOME": "/data/huggingface"})
)
vol = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


def load_data():
    from datasets import ClassLabel, DatasetDict, Value, load_dataset

    raw = load_dataset(**DATASET)
    feature = raw[SPLITS["train"]].features[LABEL_COLUMN]
    if ID2LABEL is not None:
        labels = [ID2LABEL[i] for i in range(len(ID2LABEL))]
    elif isinstance(feature, ClassLabel):
        labels = feature.names
    else:
        labels = [str(value) for value in sorted(raw[SPLITS["train"]].unique(LABEL_COLUMN))]

    ds = DatasetDict()
    for role, split in SPLITS.items():
        if split is not None:
            data = raw[split].select_columns([INPUT_COLUMN, LABEL_COLUMN])
            data = data.rename_columns({INPUT_COLUMN: "text", LABEL_COLUMN: "label"})
            # CSV labels use large_string; ClassLabel maps names from string storage.
            if data.features["label"].dtype == "large_string":
                data = data.cast_column("label", Value("string"))
            ds[role] = data.cast_column("label", ClassLabel(names=labels))
    if "validation" not in ds:
        split = ds["train"].train_test_split(
            test_size=VALIDATION_FRACTION, seed=SEED, stratify_by_column="label"
        )
        ds["train"], ds["validation"] = split["train"], split["test"]
    return ds, dict(enumerate(labels))


def tokenize(examples, tokenizer):
    encoded = tokenizer(examples["text"], truncation=True, max_length=MAX_LENGTH)
    encoded["labels"] = examples["label"]
    return encoded


def compute_metrics(pred):
    from sklearn.metrics import accuracy_score, f1_score

    predictions = pred.predictions.argmax(axis=-1)
    return {
        "accuracy": accuracy_score(pred.label_ids, predictions),
        "f1_micro": f1_score(pred.label_ids, predictions, average="micro", zero_division=0),
        "f1_macro": f1_score(
            pred.label_ids,
            predictions,
            labels=list(range(pred.predictions.shape[1])),
            average="macro",
            zero_division=0,
        ),
    }


@app.function(
    image=image,
    volumes={str(DATA_ROOT): vol},
    gpu=GPU,
    cpu=CPU,
    memory=MEMORY_MB,
    timeout=TIMEOUT,
)
def train_model(smoke: bool = False):
    from scipy.special import softmax
    from sklearn.metrics import classification_report
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        DataCollatorWithPadding,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    set_seed(SEED)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = DATA_ROOT / "runs" / f"{RUN_NAME}-{'smoke' if smoke else 'full'}-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        ds, id2label = load_data()
        if smoke:
            for split in ds:
                ds[split] = (
                    ds[split].shuffle(seed=SEED).select(range(min(SMOKE_ROWS, len(ds[split]))))
                )
        tokenizer = AutoTokenizer.from_pretrained(CHECKPOINT, revision=MODEL_REVISION)
        tokenized = ds.map(
            tokenize,
            fn_kwargs={"tokenizer": tokenizer},
            batched=True,
            remove_columns=ds["train"].column_names,
        )
        model = AutoModelForSequenceClassification.from_pretrained(
            CHECKPOINT,
            revision=MODEL_REVISION,
            num_labels=len(id2label),
            id2label=id2label,
            label2id={name: i for i, name in id2label.items()},
            problem_type="single_label_classification",
            attn_implementation="sdpa",
        )
        args = TrainingArguments(
            output_dir=str(run_dir / "checkpoints"),
            num_train_epochs=NUM_TRAIN_EPOCHS,
            max_steps=SMOKE_STEPS if smoke else -1,
            learning_rate=LEARNING_RATE,
            per_device_train_batch_size=BATCH_SIZE,
            per_device_eval_batch_size=BATCH_SIZE,
            bf16=True,
            optim="adamw_torch_fused",
            logging_steps=1 if smoke else 50,
            eval_strategy="epoch",
            save_strategy="epoch",
            save_total_limit=2,
            load_best_model_at_end=True,
            metric_for_best_model="f1_macro",
            report_to="none",
            seed=SEED,
        )
        trainer = Trainer(
            model=model,
            args=args,
            train_dataset=tokenized["train"],
            eval_dataset=tokenized["validation"],
            data_collator=DataCollatorWithPadding(tokenizer),
            processing_class=tokenizer,
            compute_metrics=compute_metrics,
        )
        training = trainer.train()
        trainer.save_model(str(run_dir / "best_model"))
        prediction = trainer.predict(tokenized["test"], metric_key_prefix="test")
        probs = softmax(prediction.predictions, axis=-1)
        predictions = probs.argmax(axis=-1)
        thresholds = []
        for threshold in CONFIDENCE_THRESHOLDS:
            accepted = probs.max(axis=-1) >= threshold
            thresholds.append(
                {
                    "threshold": threshold,
                    "coverage": float(accepted.mean()),
                    "accuracy": float(
                        (predictions[accepted] == prediction.label_ids[accepted]).mean()
                    )
                    if accepted.any()
                    else None,
                }
            )
        results = {
            "smoke": smoke,
            "split_sizes": {split: len(data) for split, data in ds.items()},
            "train": training.metrics,
            "test": prediction.metrics,
            "thresholds": thresholds,
            "classification_report": classification_report(
                prediction.label_ids,
                predictions,
                labels=list(id2label),
                target_names=list(id2label.values()),
                output_dict=True,
                zero_division=0,
            ),
        }
        (run_dir / "metrics.json").write_text(json.dumps(results, indent=2) + "\n")
        shutil.copyfile(__file__, run_dir / "trainer.py")
        print(
            json.dumps(
                {key: value for key, value in results.items() if key != "classification_report"},
                indent=2,
            )
        )
        print(
            f"Artifacts: uv run modal volume get {VOLUME_NAME} "
            f"{run_dir.relative_to(DATA_ROOT)} ./runs"
        )
    finally:
        vol.commit()


@app.local_entrypoint()
def main(smoke: bool = False):
    train_model.remote(smoke)
