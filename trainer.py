"""Fine-tune ModernBERT on Modal; adapted from Chris Levy's December 2024 trainer.

Original blog post:
https://drchrislevy.com/blog/blog_post?fpath=posts%2Fmodern_bert%2Fmodern_bert.ipynb

Run from the repository root:
    uv run modal run trainer.py --smoke
    uv run modal run trainer.py
    uv run modal run trainer.py --dataset emotion

Reports are downloaded to ~/.cache/modernbert/runs/.
Model weights and predictions stay on the Modal Volume configured below.
"""

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import modal

# ---------------------------------- SETUP BEGIN ----------------------------------#
# Add or edit datasets here; the training/evaluation code below is dataset-independent.
DATASETS = {
    "banking77": {
        "load": {
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
        },
        "input_column": "text",
        "label_column": "category",
        "splits": {"train": "train", "validation": None, "test": "test"},
        "id2label": None,  # Infer the sorted string categories from training only.
        "clean_training": True,  # Remove duplicate texts and texts also in validation/test.
    },
    "emotion": {
        "load": {
            "path": "dair-ai/emotion",
            "name": "split",
            "revision": "cab853a1dbdf4c42c2b3ef2173804746df8825fe",
        },
        "input_column": "text",
        "label_column": "label",
        "splits": {"train": "train", "validation": "validation", "test": "test"},
        "id2label": {0: "sadness", 1: "joy", 2: "love", 3: "anger", 4: "fear", 5: "surprise"},
        "clean_training": False,
    },
}
CHECKPOINTS = {
    "base": ("answerdotai/ModernBERT-base", "8949b909ec900327062f0ebf497f51aef5e6f0c8"),
    "large": ("answerdotai/ModernBERT-large", "45bb4654a4d5aaff24dd11d4781fa46d39bf8c13"),
}
VOLUME_NAME = "modern_bert_runs"
DATA_ROOT = Path("/data")
LOCAL_RESULTS_DIR = Path.home() / ".cache" / "modernbert" / "runs"
GPU = "L4"


DEFAULTS = {
    "dataset": "banking77",  # Change this default or pass --dataset.
    "model_size": "base",
    "batch_size": 32,
    "num_train_epochs": 2,
    "learning_rate": 5e-5,
    "max_length": 128,
    "seed": 42,
    "validation_fraction": 0.1,
    "train_per_class": 0,  # 0 uses all training examples after validation is split off.
    "target_accuracy": 0.95,
    "smoke": False,
}


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


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def load_data(settings, config):
    from datasets import ClassLabel, DatasetDict, Value, load_dataset
    from sklearn.model_selection import train_test_split

    raw = load_dataset(**settings["load"])
    text_column, label_column = settings["input_column"], settings["label_column"]
    training = raw[settings["splits"]["train"]]
    if settings["id2label"] is None:
        feature = training.features[label_column]
        labels = (
            feature.names
            if isinstance(feature, ClassLabel)
            else [str(value) for value in sorted(training.unique(label_column))]
        )
    else:
        labels = [settings["id2label"][i] for i in range(len(settings["id2label"]))]
    ds = DatasetDict()
    for role, split in settings["splits"].items():
        if split is None:
            continue
        data = raw[split].select_columns([text_column, label_column])
        data = data.rename_columns({text_column: "text", label_column: "label"})
        # CSV labels use large_string; ClassLabel maps names only from string storage.
        if data.features["label"].dtype == "large_string":
            data = data.cast_column("label", Value("string"))
        data = data.cast_column("label", ClassLabel(names=labels))
        if any(label is None or not 0 <= label < len(labels) for label in data["label"]):
            raise ValueError(f"{split}: labels must be class IDs in 0..{len(labels) - 1}")
        ds[role] = data.add_column("example_id", [f"{split}-{i}" for i in range(len(data))])
    audit = {"original_sizes": {split: len(data) for split, data in ds.items()}}

    if settings["clean_training"]:

        def normalize(text):
            return " ".join(text.casefold().split())

        held_out = {
            normalize(text)
            for split in ("validation", "test")
            if split in ds
            for text in ds[split]["text"]
        }
        seen, keep = {}, []
        for i, row in enumerate(ds["train"]):
            text = normalize(row["text"])
            if text in held_out:
                continue
            if text in seen and seen[text] != row["label"]:
                raise ValueError(f"Conflicting training labels for {text!r}")
            if text not in seen:
                seen[text] = row["label"]
                keep.append(i)
        audit["removed_training_rows"] = len(ds["train"]) - len(keep)
        ds["train"] = ds["train"].select(keep)

    if "validation" not in ds:
        train_ids, validation_ids = train_test_split(
            range(len(ds["train"])),
            test_size=config["validation_fraction"],
            random_state=config["seed"],
            stratify=ds["train"]["label"],
        )
        ds["validation"] = ds["train"].select(validation_ids)
        ds["train"] = ds["train"].select(train_ids)
    if config["train_per_class"]:
        shuffled = ds["train"].shuffle(seed=config["seed"])
        counts, keep = [0] * len(labels), []
        for i, label in enumerate(shuffled["label"]):
            if counts[label] < config["train_per_class"]:
                counts[label] += 1
                keep.append(i)
        if min(counts) < config["train_per_class"]:
            raise ValueError("Not enough training examples for the requested train_per_class")
        ds["train"] = shuffled.select(keep)
    if config["smoke"]:
        ds = DatasetDict(
            {
                split: data.shuffle(seed=config["seed"]).select(range(min(128, len(data))))
                for split, data in ds.items()
            }
        )
    return ds, labels, audit


def tokenizer_function_logic(examples, tokenizer, max_length):
    # A standalone function makes Dataset.map caching independent of the Modal class.
    encoded = tokenizer(examples["text"], truncation=True, max_length=max_length)
    encoded["labels"] = examples["label"]  # One integer class ID per sequence.
    return encoded


def check_classification_batch(model, collator, tokenized):
    """Check the actual model inputs and cross-entropy loss before training."""
    import torch
    from torch.nn.functional import cross_entropy

    batch = collator([tokenized[i] for i in range(min(4, len(tokenized)))])
    if set(batch) - {"labels", *collator.tokenizer.model_input_names}:
        raise ValueError(f"Unexpected model input columns: {list(batch)}")
    labels = batch["labels"]
    if labels.dtype != torch.long or labels.ndim != 1:
        raise ValueError("Classification labels must be int64 with shape [batch_size]")
    if not ((labels >= 0) & (labels < model.config.num_labels)).all():
        raise ValueError("Classification label is outside the model's class vocabulary")
    was_training = model.training
    model.eval()
    try:
        with torch.no_grad():
            output = model(**{key: value.to(model.device) for key, value in batch.items()})
        if output.logits.shape != (len(labels), model.config.num_labels):
            raise ValueError("Classifier logits must have shape [batch_size, num_labels]")
        if output.loss is None or output.loss.ndim != 0 or not torch.isfinite(output.loss):
            raise ValueError("Classifier must return a finite scalar loss")
        expected = cross_entropy(output.logits.float(), labels.to(model.device))
        torch.testing.assert_close(output.loss.float(), expected, atol=1e-5, rtol=1e-5)
        return {
            "columns": sorted(batch),
            "labels_dtype": str(labels.dtype),
            "labels_shape": list(labels.shape),
            "logits_shape": list(output.logits.shape),
            "problem_type": model.config.problem_type,
            "cross_entropy": output.loss.item(),
        }
    finally:
        model.train(was_training)


def classification_metrics(probabilities, labels):
    import numpy as np
    from sklearn.metrics import accuracy_score, f1_score, log_loss

    probs = np.asarray(probabilities, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.int64)
    predictions = probs.argmax(axis=1)
    correct = predictions == labels
    confidence = probs.max(axis=1)
    targets = np.eye(probs.shape[1])[labels]
    bins = np.minimum((confidence * 15).astype(int), 14)
    ece = 0.0
    for index in range(15):
        mask = bins == index
        if mask.any():
            ece += mask.mean() * abs(correct[mask].mean() - confidence[mask].mean())
    return {
        "accuracy": float(accuracy_score(labels, predictions)),
        "f1_micro": float(f1_score(labels, predictions, average="micro", zero_division=0)),
        "f1_macro": float(
            f1_score(
                labels,
                predictions,
                labels=list(range(probs.shape[1])),
                average="macro",
                zero_division=0,
            )
        ),
        "nll": float(log_loss(labels, probs, labels=list(range(probs.shape[1])))),
        "brier": float(np.square(probs - targets).sum(axis=1).mean()),
        "ece_15_bins": float(ece),
        "n": len(labels),
    }


def select_threshold(probabilities, labels, target_accuracy):
    """Maximize empirical validation coverage at the requested selective accuracy.

    Ties are inseparable under a threshold. None means reject everything. This
    validation estimate cannot guarantee the target accuracy on future data.
    """
    import numpy as np

    probs = np.asarray(probabilities)
    labels = np.asarray(labels)
    confidence = probs.max(axis=1)
    order = np.argsort(-confidence, kind="stable")
    scores = confidence[order]
    cumulative_correct = np.cumsum(probs.argmax(axis=1)[order] == labels[order])
    group_ends = np.r_[np.flatnonzero(scores[:-1] != scores[1:]), len(scores) - 1]
    eligible = group_ends[cumulative_correct[group_ends] / (group_ends + 1) >= target_accuracy]
    return float(scores[eligible[-1]]) if len(eligible) else None


def selective_metrics(probabilities, labels, threshold):
    import numpy as np

    probs = np.asarray(probabilities)
    labels = np.asarray(labels)
    accepted = (
        np.zeros(len(labels), dtype=bool) if threshold is None else probs.max(axis=1) >= threshold
    )
    return {
        "coverage": float(accepted.mean()),
        "accepted": int(accepted.sum()),
        "accuracy": float((probs.argmax(axis=1)[accepted] == labels[accepted]).mean())
        if accepted.any()
        else None,
    }


@app.cls(
    image=image,
    volumes={str(DATA_ROOT): vol},
    gpu=GPU,
    cpu=4,
    memory=16384,
    timeout=60 * 30,
    scaledown_window=60,
)
class Trainer:
    @modal.enter()
    def setup(self):
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("This experiment requires a CUDA GPU")
        torch.set_float32_matmul_precision("high")

    def compute_metrics(self, pred):
        import numpy as np
        from scipy.special import softmax

        return classification_metrics(
            softmax(pred.predictions.astype(np.float64), axis=-1), pred.label_ids
        )

    @modal.method()
    def train_model(self, config: dict, run_name: str, source: dict):
        import importlib.metadata
        import time

        import numpy as np
        import torch
        from transformers import (
            AutoConfig,
            AutoModelForSequenceClassification,
            AutoTokenizer,
            DataCollatorWithPadding,
            TrainingArguments,
            set_seed,
        )
        from transformers import Trainer as HFTrainer

        self.config = config
        if not re.fullmatch(r"[A-Za-z0-9_-]+", run_name):
            raise ValueError("run_name must contain only letters, numbers, hyphens and underscores")
        run_dir = DATA_ROOT / "runs" / run_name
        run_dir.mkdir(parents=True, exist_ok=False)  # Never delete a previous run.
        try:
            set_seed(self.config["seed"])  # Before initializing the classification head.
            checkpoint, revision = CHECKPOINTS[self.config["model_size"]]
            dataset_config = DATASETS[self.config["dataset"]]
            ds, labels, data_audit = load_data(dataset_config, config)
            id2label = dict(enumerate(labels))
            label2id = {v: k for k, v in id2label.items()}
            self.tokenizer = AutoTokenizer.from_pretrained(checkpoint, revision=revision)
            tokenized = ds.map(
                tokenizer_function_logic,
                fn_kwargs={"tokenizer": self.tokenizer, "max_length": self.config["max_length"]},
                batched=True,
                remove_columns=ds["train"].column_names,
                desc="Tokenizing",
            )
            configuration = AutoConfig.from_pretrained(checkpoint, revision=revision)
            configuration.id2label = id2label
            configuration.label2id = label2id
            configuration.num_labels = len(labels)
            configuration.problem_type = "single_label_classification"
            # Native PyTorch SDPA avoids compiling an external flash-attn package.
            model = AutoModelForSequenceClassification.from_pretrained(
                checkpoint, revision=revision, config=configuration, attn_implementation="sdpa"
            )
            training_args = TrainingArguments(
                output_dir=str(run_dir / "checkpoints"),
                num_train_epochs=self.config["num_train_epochs"],
                max_steps=5 if self.config["smoke"] else -1,
                learning_rate=self.config["learning_rate"],
                per_device_train_batch_size=self.config["batch_size"],
                per_device_eval_batch_size=self.config["batch_size"],
                bf16=True,
                optim="adamw_torch_fused",
                logging_strategy="steps",
                logging_steps=1 if self.config["smoke"] else 50,
                eval_strategy="epoch",
                save_strategy="epoch",
                save_total_limit=2,
                load_best_model_at_end=True,
                metric_for_best_model="f1_macro",
                greater_is_better=True,
                report_to="none",
                run_name=run_name,
                seed=self.config["seed"],
                data_seed=self.config["seed"],
                disable_tqdm=True,
            )
            trainer = HFTrainer(
                model=model,
                args=training_args,
                train_dataset=tokenized["train"],
                eval_dataset=tokenized["validation"],
                data_collator=DataCollatorWithPadding(self.tokenizer, pad_to_multiple_of=8),
                processing_class=self.tokenizer,  # Formerly tokenizer=.
                compute_metrics=self.compute_metrics,
            )
            manifest = {
                "run_name": run_name,
                "config": config,
                "source": source,
                "model": {"name": checkpoint, "revision": revision},
                "dataset": {"settings": dataset_config, **data_audit},
                "labels": labels,
                "classification_batch": check_classification_batch(
                    trainer.model, trainer.data_collator, tokenized["train"]
                ),
                "split_ids": {split: list(ds[split]["example_id"]) for split in ds},
                "packages": {
                    package: importlib.metadata.version(package)
                    for package in (
                        "torch",
                        "transformers",
                        "datasets",
                        "accelerate",
                        "scikit-learn",
                    )
                },
                "hardware": {"gpu": torch.cuda.get_device_name(), "cuda": torch.version.cuda},
                "smoke_only": self.config["smoke"],
            }
            write_json(run_dir / "manifest.json", manifest)
            started = time.perf_counter()
            training = trainer.train()
            training_seconds = time.perf_counter() - started
            # load_best_model_at_end has restored the validation-selected weights.
            trainer.save_model(str(run_dir / "best_model"))
            trainer.save_state()
            validation, validation_probs = self.eval_model(
                trainer, tokenized["validation"], ds["validation"], run_dir, "validation"
            )
            threshold = select_threshold(
                validation_probs, ds["validation"]["label"], self.config["target_accuracy"]
            )
            # Use the frozen validation threshold on test. Never optimize it on test.
            test, test_probs = self.eval_model(
                trainer, tokenized["test"], ds["test"], run_dir, "test"
            )
            summary = {
                "run_name": run_name,
                "smoke_only": self.config["smoke"],
                "split_sizes": {split: len(ds[split]) for split in ds},
                "training_seconds": training_seconds,
                "training": training.metrics,
                "best_checkpoint": trainer.state.best_model_checkpoint,
                "best_validation_f1_macro": trainer.state.best_metric,
                "validation": validation,
                "test": test,
                "selective": {
                    "target_validation_accuracy": self.config["target_accuracy"],
                    "threshold": threshold,
                    "validation": selective_metrics(
                        validation_probs, ds["validation"]["label"], threshold
                    ),
                    "test": selective_metrics(test_probs, ds["test"]["label"], threshold),
                },
                "peak_gpu_allocated_gb": torch.cuda.max_memory_allocated() / 1024**3,
                "volume": VOLUME_NAME,
                "artifact_path": f"runs/{run_name}",
            }
            write_json(run_dir / "summary.json", summary)
            write_json(run_dir / "training_log.json", trainer.state.log_history)
            print(json.dumps(summary, indent=2))
            del model, trainer
            torch.cuda.empty_cache()
            # Verify that the saved checkpoint loads with the correct label mapping.
            restored = AutoModelForSequenceClassification.from_pretrained(run_dir / "best_model")
            assert restored.config.id2label == id2label
            assert np.isfinite(test_probs).all()
            return summary
        finally:
            vol.commit()  # Persist checkpoints and partial artifacts even on failure.

    def eval_model(self, trainer, tokenized, raw, run_dir, split):
        import time

        import numpy as np
        import torch
        from scipy.special import softmax
        from sklearn.metrics import classification_report

        torch.cuda.synchronize()
        started = time.perf_counter()
        prediction = trainer.predict(tokenized, metric_key_prefix=split)
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - started
        probs = softmax(prediction.predictions.astype(np.float64), axis=-1)
        np.savez_compressed(
            run_dir / f"{split}_predictions.npz",
            logits=prediction.predictions,
            probabilities=probs,
            labels=prediction.label_ids,
            example_ids=np.asarray(raw["example_id"]),
        )
        report = classification_report(
            prediction.label_ids,
            probs.argmax(axis=1),
            labels=list(range(probs.shape[1])),
            target_names=[trainer.model.config.id2label[i] for i in range(probs.shape[1])],
            output_dict=True,
            zero_division=0,
        )
        write_json(run_dir / f"{split}_classification_report.json", report)
        metrics = classification_metrics(probs, prediction.label_ids)
        metrics.update(
            evaluation_seconds=elapsed,
            examples_per_second=len(raw) / elapsed,
            # Batched throughput, NOT online single-request latency.
            evaluation_batch_size=self.config["batch_size"],
        )
        return metrics, probs


@app.local_entrypoint()
def main(
    dataset: str = DEFAULTS["dataset"],
    smoke: bool = DEFAULTS["smoke"],
    model_size: str = DEFAULTS["model_size"],
    epochs: int = DEFAULTS["num_train_epochs"],
    learning_rate: float = DEFAULTS["learning_rate"],
    batch_size: int = DEFAULTS["batch_size"],
    max_length: int = DEFAULTS["max_length"],
    seed: int = DEFAULTS["seed"],
    train_per_class: int = DEFAULTS["train_per_class"],
    target_accuracy: float = DEFAULTS["target_accuracy"],
    gpu: str = GPU,
):
    config = dict(
        DEFAULTS,
        dataset=dataset,
        model_size=model_size,
        num_train_epochs=epochs,
        learning_rate=learning_rate,
        batch_size=batch_size,
        max_length=max_length,
        seed=seed,
        train_per_class=train_per_class,
        target_accuracy=target_accuracy,
        smoke=smoke,
    )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    mode = "smoke" if smoke else "full"
    dataset_slug = re.sub(r"[^A-Za-z0-9_-]+", "-", dataset)
    run_name = f"{dataset_slug}-{model_size}-{mode}-s{seed}-{stamp}-{uuid4().hex[:6]}"
    script = Path(__file__)
    source = {"sha256": {script.name: hashlib.sha256(script.read_bytes()).hexdigest()}}
    try:
        source["git_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        source["git_dirty"] = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], text=True, stderr=subprocess.DEVNULL
            )
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass  # The script also runs outside a Git checkout.
    print(f"Running {run_name} on {gpu}", flush=True)
    summary = Trainer.with_options(gpu=gpu)().train_model.remote(config, run_name, source)
    destination = LOCAL_RESULTS_DIR / run_name
    destination.mkdir(parents=True, exist_ok=False)
    # Download reports; weights and full-precision predictions remain on the Volume.
    for name in ("summary.json", "manifest.json", "training_log.json"):
        with (destination / name).open("wb") as file:
            for chunk in vol.read_file(f"runs/{run_name}/{name}"):
                file.write(chunk)
    print(json.dumps(summary, indent=2))
    print(f"Local reports: {destination}")
    print(
        f"Artifacts: uv run modal volume get {VOLUME_NAME} runs/{run_name} "
        f'"{destination / "artifacts"}"'
    )
