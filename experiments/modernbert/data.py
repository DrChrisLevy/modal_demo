"""Pinned Banking77 data, with validation drawn exclusively from training."""

import json
from urllib.request import urlopen

DATA_REVISION = "9d081458ff52e53cf7e848f414e6e9344e4e6696"
DATA_URL = (
    "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/"
    f"{DATA_REVISION}/banking_data"
)


def normalize_text(text):
    return " ".join(text.casefold().split())


def clean_training_rows(train, test):
    """Remove train duplicates and test-text overlap without using test labels."""
    test_texts = {normalize_text(row["text"]) for row in test}
    seen = {}
    kept, duplicates, overlap = [], 0, 0
    for row in train:
        text = normalize_text(row["text"])
        if text in test_texts:
            overlap += 1
        elif text in seen:
            if seen[text] != row["label"]:
                raise ValueError(f"Conflicting labels for training text: {text!r}")
            duplicates += 1
        else:
            kept.append(row)
            seen[text] = row["label"]
    return kept, {"removed_training_duplicates": duplicates, "removed_test_text_overlap": overlap}


def prepare_banking77(seed=42, validation_fraction=0.1, train_per_class=0, smoke=False):
    from datasets import ClassLabel, Dataset, DatasetDict, load_dataset
    from sklearn.model_selection import train_test_split

    # PolyAI's HF Python loading script is unsupported by datasets >= 4.
    # Use its original versioned CSVs instead of enabling remote code.
    with urlopen(f"{DATA_URL}/categories.json", timeout=60) as response:
        labels = sorted(json.load(response))
    label2id = {label: i for i, label in enumerate(labels)}
    original = load_dataset(
        "csv", data_files={split: f"{DATA_URL}/{split}.csv" for split in ("train", "test")}
    )
    rows = {
        split: [
            {"text": row["text"], "label": label2id[row["category"]], "example_id": f"{split}-{i}"}
            for i, row in enumerate(original[split])
        ]
        for split in original
    }
    clean, audit = clean_training_rows(rows["train"], rows["test"])
    train, validation = train_test_split(
        clean,
        test_size=validation_fraction,
        random_state=seed,
        stratify=[row["label"] for row in clean],
    )
    ds = DatasetDict(
        {
            split: Dataset.from_list(data).cast_column("label", ClassLabel(names=labels))
            for split, data in {
                "train": train,
                "validation": validation,
                "test": rows["test"],
            }.items()
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
        original_sizes={split: len(data) for split, data in rows.items()},
        split_sizes={split: len(data) for split, data in ds.items()},
        deduplication="casefold and collapse whitespace; preserve official test",
        validation_fraction=validation_fraction,
        seed=seed,
    )
    return ds, labels, audit
