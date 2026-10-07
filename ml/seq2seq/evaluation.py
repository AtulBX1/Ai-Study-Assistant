"""Text-generation metrics for sequence-to-sequence summaries."""

from collections.abc import Sequence


def repeated_trigram_rate(text: str) -> float:
    tokens = text.split()
    trigrams = [tuple(tokens[index : index + 3]) for index in range(len(tokens) - 2)]
    if not trigrams:
        return 0.0
    return (len(trigrams) - len(set(trigrams))) / len(trigrams)


def compute_metrics(
    predictions: Sequence[str], references: Sequence[str]
) -> dict[str, float]:
    """Compute corpus ROUGE-1/2/L, BLEU, length, and repeated-trigram rate."""
    if len(predictions) != len(references) or not predictions:
        raise ValueError(
            "Predictions and references must be equally sized and nonempty."
        )
    from rouge_score import rouge_scorer
    from sacrebleu import corpus_bleu

    scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=True)
    rouge = {name: 0.0 for name in ("rouge1", "rouge2", "rougeL")}
    for prediction, reference in zip(predictions, references, strict=True):
        scores = scorer.score(reference, prediction)
        for name in rouge:
            rouge[name] += scores[name].fmeasure
    count = len(predictions)
    bleu = corpus_bleu(list(predictions), [list(references)], tokenize="13a").score
    return {
        "rouge1": rouge["rouge1"] / count,
        "rouge2": rouge["rouge2"] / count,
        "rougeL": rouge["rougeL"] / count,
        "bleu": bleu,
        "average_summary_length": sum(len(item.split()) for item in predictions)
        / count,
        "repeated_trigram_rate": sum(
            repeated_trigram_rate(item) for item in predictions
        )
        / count,
    }
