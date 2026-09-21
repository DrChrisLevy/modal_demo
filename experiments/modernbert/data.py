"""Normalize configured datasets for single-label text classification."""

from dataclasses import dataclass
from numbers import Integral


@dataclass(frozen=True)
class DatasetConfig:
    name: str
    name_config: str | None = None
    revision: str | None = None
    data_files: dict[str, str] | None = None
    input_column: str = "text"
    label_column: str = "label"
    train_split: str = "train"
    validation_split: str | None = "validation"  # None creates a stratified training holdout.
    test_split: str = "test"
    # Integer IDs must be 0..N-1. String targets are matched to these names.
    # None infers names from ClassLabel metadata or the training targets only.
    id2label: dict[int, str] | None = None


def normalize_text(text):
    return " ".join(text.casefold().split())


def clean_training_rows(train, holdout):
    """Optional preparation hook: remove duplicates and holdout-text overlap."""
    holdout_texts = {normalize_text(row["text"]) for row in holdout}
    seen = {}
    kept, duplicates, overlap = [], 0, 0
    for row in train:
        text = normalize_text(row["text"])
        if text in holdout_texts:
            overlap += 1
        elif text in seen:
            if seen[text] != row["label"]:
                raise ValueError(f"Conflicting labels for training text: {text!r}")
            duplicates += 1
        else:
            kept.append(row)
            seen[text] = row["label"]
    return kept, {
        "removed_training_duplicates": duplicates,
        "removed_holdout_text_overlap": overlap,
    }


def label_names(training, config):
    """Resolve the class vocabulary without reading validation/test targets."""
    from datasets import ClassLabel

    feature = training.features[config.label_column]
    if config.id2label is not None:
        if set(config.id2label) != set(range(len(config.id2label))):
            raise ValueError("id2label keys must be consecutive integer IDs starting at 0")
        labels = [config.id2label[i] for i in range(len(config.id2label))]
    elif isinstance(feature, ClassLabel):
        labels = feature.names
    else:
        targets = list(training[config.label_column])
        if all(isinstance(value, str) for value in targets):
            labels = sorted(set(targets))
        elif all(isinstance(value, Integral) and not isinstance(value, bool) for value in targets):
            ids = sorted(set(targets))
            if ids != list(range(len(ids))):
                raise ValueError(
                    "Integer labels must be 0..N-1; configure id2label for missing classes"
                )
            labels = [str(value) for value in ids]
        else:
            raise ValueError("Targets must be scalar integer IDs or strings, not floats or lists")
    if (
        len(labels) < 2
        or any(not isinstance(label, str) or not label for label in labels)
        or len(set(labels)) != len(labels)
    ):
        raise ValueError(
            "Single-label classification needs at least two unique, nonempty class names"
        )
    return labels


def prepare_classification_dataset(
    original,
    config,
    *,
    seed=42,
    validation_fraction=0.1,
    train_per_class=0,
    smoke=False,
    prepare_train=None,
):
    from datasets import ClassLabel, Dataset, DatasetDict
    from sklearn.model_selection import train_test_split

    splits = {"train": config.train_split, "test": config.test_split}
    if config.validation_split is not None:
        splits["validation"] = config.validation_split
    if len(set(splits.values())) != len(splits):
        raise ValueError("Training, validation and test must use distinct source splits")
    for split in splits.values():
        if split not in original or not len(original[split]):
            raise ValueError(f"Missing or empty configured split: {split}")
        missing = {config.input_column, config.label_column} - set(original[split].column_names)
        if missing:
            raise ValueError(f"Split {split!r} is missing configured columns: {sorted(missing)}")

    labels = label_names(original[config.train_split], config)
    label2id = {label: i for i, label in enumerate(labels)}
    train_feature = original[config.train_split].features[config.label_column]
    rows = {}
    for role, split in splits.items():
        feature = original[split].features[config.label_column]
        if (
            isinstance(train_feature, ClassLabel)
            and isinstance(feature, ClassLabel)
            and feature.names != train_feature.names
        ):
            raise ValueError(f"ClassLabel ordering differs between training and {split!r}")
        rows[role] = []
        for i, row in enumerate(original[split]):
            text, target = row[config.input_column], row[config.label_column]
            if not isinstance(text, str):
                raise ValueError(f"{split}[{i}]: input must be a string")
            if isinstance(target, str):
                if target not in label2id:
                    raise ValueError(f"{split}[{i}]: unknown class {target!r}")
                label = label2id[target]
            elif isinstance(target, Integral) and not isinstance(target, bool):
                label = int(target)
                if not 0 <= label < len(labels):
                    raise ValueError(
                        f"{split}[{i}]: label ID {label} is outside 0..{len(labels) - 1}"
                    )
            else:
                raise ValueError(f"{split}[{i}]: target must be a scalar integer ID or string")
            rows[role].append({"text": text, "label": label, "example_id": f"{split}-{i}"})

    audit = {"original_sizes": {split: len(data) for split, data in rows.items()}}
    if prepare_train is not None:
        # Pass only held-out text to the hook, never validation/test targets.
        holdout = [
            {"text": row["text"]} for role in ("validation", "test") for row in rows.get(role, [])
        ]
        rows["train"], preparation_audit = prepare_train(rows["train"], holdout)
        audit.update(preparation_audit)
    if config.validation_split is None:
        rows["train"], rows["validation"] = train_test_split(
            rows["train"],
            test_size=validation_fraction,
            random_state=seed,
            stratify=[row["label"] for row in rows["train"]],
        )
    ds = DatasetDict(
        {
            split: Dataset.from_list(data).cast_column("label", ClassLabel(names=labels))
            for split, data in rows.items()
        }
    )
    if train_per_class:
        shuffled = ds["train"].shuffle(seed=seed)
        counts = [0] * len(labels)
        indices = []
        for i, row in enumerate(shuffled):
            if counts[row["label"]] < train_per_class:
                indices.append(i)
                counts[row["label"]] += 1
        if min(counts) < train_per_class:
            raise ValueError(
                f"Requested {train_per_class}/class, but smallest class has {min(counts)}"
            )
        ds["train"] = shuffled.select(indices)
    if smoke:
        ds = DatasetDict(
            {
                split: data.shuffle(seed=seed).select(range(min(128, len(data))))
                for split, data in ds.items()
            }
        )
    audit.update(
        split_sizes={split: len(data) for split, data in ds.items()},
        preparation=prepare_train.__name__ if prepare_train is not None else None,
        validation_fraction=validation_fraction if config.validation_split is None else None,
        seed=seed,
    )
    return ds, labels, audit


def load_classification_dataset(config, **preparation_options):
    from datasets import load_dataset

    original = load_dataset(
        config.name,
        name=config.name_config,
        revision=config.revision,
        data_files=config.data_files,
    )
    return prepare_classification_dataset(original, config, **preparation_options)
