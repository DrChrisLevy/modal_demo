"""Fine-tune ModernBERT on Modal; adapted from Chris Levy's December 2024 trainer.

Original blog post:
https://drchrislevy.com/blog/blog_post?fpath=posts%2Fmodern_bert%2Fmodern_bert.ipynb

Run from the repository root:
    uv run modal run -m experiments.modernbert.trainer --smoke
    uv run modal run -m experiments.modernbert.trainer
"""

import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import modal

from experiments.modernbert.data import (
    DatasetConfig,
    clean_training_rows,
    load_classification_dataset,
)
from experiments.modernbert.evaluation import (
    classification_metrics,
    select_threshold,
    selective_metrics,
)

# ---------------------------------- SETUP BEGIN ----------------------------------#
# Add or edit datasets here; the training/evaluation code below is dataset-independent.
DATASETS = {
    "banking77": DatasetConfig(
        name="csv",  # The original HF Python loading script is no longer supported.
        data_files={
            "train": (
                "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/"
                "9d081458ff52e53cf7e848f414e6e9344e4e6696/banking_data/train.csv"
            ),
            "test": (
                "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/"
                "9d081458ff52e53cf7e848f414e6e9344e4e6696/banking_data/test.csv"
            ),
        },
        input_column="text",
        label_column="category",
        train_split="train",
        validation_split=None,  # Create validation from training.
        test_split="test",
        id2label=None,  # Infer the sorted string categories from training only.
    ),
    "emotion": DatasetConfig(
        name="dair-ai/emotion",
        name_config="split",
        revision="cab853a1dbdf4c42c2b3ef2173804746df8825fe",
        input_column="text",
        label_column="label",
        train_split="train",
        validation_split="validation",  # Preserve the supplied validation split.
        test_split="test",
        id2label={0: "sadness", 1: "joy", 2: "love", 3: "anger", 4: "fear", 5: "surprise"},
    ),
}
# Clean Banking77 before splitting off validation: remove duplicate training texts
# and training texts that also appear in the test set.
DATA_PREPARATION = {"banking77": clean_training_rows}
CHECKPOINTS = {
    "base": ("answerdotai/ModernBERT-base", "8949b909ec900327062f0ebf497f51aef5e6f0c8"),
    "large": ("answerdotai/ModernBERT-large", "45bb4654a4d5aaff24dd11d4781fa46d39bf8c13"),
}
VOLUME_NAME = "modernbert-banking77"
DATA_ROOT = Path("/data")
GPU = "L4"


@dataclass(frozen=True)
class Config:
    dataset: str = "banking77"  # Change this default or pass --dataset.
    model_size: str = "base"
    batch_size: int = 32
    num_train_epochs: int = 2
    learning_rate: float = 5e-5
    max_length: int = 128
    seed: int = 42
    validation_fraction: float = 0.1
    train_per_class: int = 0  # 0 uses all training examples after validation is split off.
    target_accuracy: float = 0.95
    smoke: bool = False

    def __post_init__(self):
        if self.dataset not in DATASETS:
            raise ValueError(f"dataset must be one of {list(DATASETS)}")
        if self.model_size not in CHECKPOINTS:
            raise ValueError(f"model_size must be one of {list(CHECKPOINTS)}")
        if self.batch_size < 1 or self.num_train_epochs < 1 or self.learning_rate <= 0:
            raise ValueError("batch size, epochs and learning rate must be positive")
        if not 1 <= self.max_length <= 8192:
            raise ValueError("max_length must be between 1 and 8192")
        if not 0 < self.validation_fraction < 1 or self.train_per_class < 0:
            raise ValueError("invalid validation fraction or train_per_class")
        if not 0 < self.target_accuracy <= 1:
            raise ValueError("target_accuracy must be in (0, 1]")


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
    .env({"HF_HOME": "/data/huggingface", "TOKENIZERS_PARALLELISM": "false"})
    .add_local_python_source("experiments")
)
vol = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


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

        self.config = Config(**config)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", run_name):
            raise ValueError("run_name must contain only letters, numbers, hyphens and underscores")
        run_dir = DATA_ROOT / "runs" / run_name
        run_dir.mkdir(parents=True, exist_ok=False)  # Never delete a previous run.
        try:
            set_seed(self.config.seed)  # Before initializing the classification head.
            checkpoint, revision = CHECKPOINTS[self.config.model_size]
            dataset_config = DATASETS[self.config.dataset]
            ds, labels, data_audit = load_classification_dataset(
                dataset_config,
                seed=self.config.seed,
                validation_fraction=self.config.validation_fraction,
                train_per_class=self.config.train_per_class,
                smoke=self.config.smoke,
                prepare_train=DATA_PREPARATION.get(self.config.dataset),
            )
            id2label = dict(enumerate(labels))
            label2id = {v: k for k, v in id2label.items()}
            self.tokenizer = AutoTokenizer.from_pretrained(checkpoint, revision=revision)
            tokenized = ds.map(
                tokenizer_function_logic,
                fn_kwargs={"tokenizer": self.tokenizer, "max_length": self.config.max_length},
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
                num_train_epochs=self.config.num_train_epochs,
                max_steps=5 if self.config.smoke else -1,
                learning_rate=self.config.learning_rate,
                per_device_train_batch_size=self.config.batch_size,
                per_device_eval_batch_size=self.config.batch_size,
                bf16=True,
                optim="adamw_torch_fused",
                logging_strategy="steps",
                logging_steps=1 if self.config.smoke else 50,
                eval_strategy="epoch",
                save_strategy="epoch",
                save_total_limit=2,
                load_best_model_at_end=True,
                metric_for_best_model="f1_macro",
                greater_is_better=True,
                report_to="none",
                run_name=run_name,
                seed=self.config.seed,
                data_seed=self.config.seed,
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
                "dataset": {"loader": asdict(dataset_config), **data_audit},
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
                "smoke_only": self.config.smoke,
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
                validation_probs, ds["validation"]["label"], self.config.target_accuracy
            )
            # Use the frozen validation threshold on test. Never optimize it on test.
            test, test_probs = self.eval_model(
                trainer, tokenized["test"], ds["test"], run_dir, "test"
            )
            summary = {
                "run_name": run_name,
                "smoke_only": self.config.smoke,
                "split_sizes": {split: len(ds[split]) for split in ds},
                "training_seconds": training_seconds,
                "training": training.metrics,
                "best_checkpoint": trainer.state.best_model_checkpoint,
                "best_validation_f1_macro": trainer.state.best_metric,
                "validation": validation,
                "test": test,
                "selective": {
                    "target_validation_accuracy": self.config.target_accuracy,
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
            evaluation_batch_size=self.config.batch_size,
        )
        return metrics, probs


@app.local_entrypoint()
def main(
    dataset: str = Config.dataset,
    smoke: bool = Config.smoke,
    model_size: str = Config.model_size,
    epochs: int = Config.num_train_epochs,
    learning_rate: float = Config.learning_rate,
    batch_size: int = Config.batch_size,
    max_length: int = Config.max_length,
    seed: int = Config.seed,
    train_per_class: int = Config.train_per_class,
    target_accuracy: float = Config.target_accuracy,
    gpu: str = GPU,
):
    config = Config(
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
    package_dir = Path(__file__).parent
    source = {
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "git_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True)),
        "sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(package_dir.glob("*.py"))
        },
    }
    print(f"Running {run_name} on {gpu}", flush=True)
    summary = Trainer.with_options(gpu=gpu)().train_model.remote(asdict(config), run_name, source)
    destination = package_dir / "results" / run_name
    destination.mkdir(parents=True, exist_ok=False)
    # Download reports; weights and full-precision predictions remain on the Volume.
    for name in ("summary.json", "manifest.json", "training_log.json"):
        with (destination / name).open("wb") as file:
            for chunk in vol.read_file(f"runs/{run_name}/{name}"):
                file.write(chunk)
    print(json.dumps(summary, indent=2))
    print(f"Local reports: {destination}")
    print(
        f"Artifacts: uv run modal volume get {VOLUME_NAME} runs/{run_name} ./artifacts/{run_name}"
    )
