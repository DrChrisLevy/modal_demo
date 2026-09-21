"""Full-precision metrics and a validation-selected abstention threshold."""


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
