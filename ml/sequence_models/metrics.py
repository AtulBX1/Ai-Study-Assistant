"""Small dependency-free classification metrics."""

from collections.abc import Sequence


def confusion_matrix(
    targets: Sequence[int], predictions: Sequence[int], num_classes: int
) -> list[list[int]]:
    """Return a matrix indexed as rows=actual class, columns=predicted class."""
    if len(targets) != len(predictions):
        raise ValueError("Targets and predictions must have the same length.")
    if num_classes < 1:
        raise ValueError("num_classes must be positive.")
    matrix = [[0 for _ in range(num_classes)] for _ in range(num_classes)]
    for target, prediction in zip(targets, predictions, strict=True):
        if not 0 <= target < num_classes or not 0 <= prediction < num_classes:
            raise ValueError("Class IDs must be within [0, num_classes).")
        matrix[target][prediction] += 1
    return matrix


def classification_metrics(
    targets: Sequence[int], predictions: Sequence[int], num_classes: int
) -> dict[str, object]:
    """Compute accuracy, macro precision/recall/F1, and a confusion matrix."""
    matrix = confusion_matrix(targets, predictions, num_classes)
    total = len(targets)
    per_class: list[dict[str, float]] = []
    for class_id in range(num_classes):
        true_positive = matrix[class_id][class_id]
        false_positive = (
            sum(matrix[row][class_id] for row in range(num_classes)) - true_positive
        )
        false_negative = sum(matrix[class_id]) - true_positive
        precision = (
            true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else 0.0
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else 0.0
        )
        f1 = (
            2 * precision * recall / (precision + recall) if precision + recall else 0.0
        )
        per_class.append({"precision": precision, "recall": recall, "f1": f1})
    return {
        "accuracy": (
            sum(matrix[index][index] for index in range(num_classes)) / total
            if total
            else 0.0
        ),
        "precision": sum(item["precision"] for item in per_class) / num_classes,
        "recall": sum(item["recall"] for item in per_class) / num_classes,
        "macro_f1": sum(item["f1"] for item in per_class) / num_classes,
        "confusion_matrix": matrix,
        "per_class": per_class,
    }
