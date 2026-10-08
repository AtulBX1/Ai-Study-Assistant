"""CoNLL-2003 word-to-subword label alignment."""

from typing import Any


def align_ner_labels(
    word_ids: list[int | None], word_labels: list[int], ignore_index: int = -100
) -> list[int]:
    """Label the first sub-token of each word and mask later sub-tokens."""
    aligned: list[int] = []
    previous_word_id: int | None = None
    for word_id in word_ids:
        if word_id is None:
            aligned.append(ignore_index)
        elif word_id != previous_word_id:
            aligned.append(word_labels[word_id])
        else:
            aligned.append(ignore_index)
        previous_word_id = word_id
    return aligned


def tokenize_and_align_labels(
    examples: dict[str, list[Any]], tokenizer: Any, max_length: int = 256
) -> dict[str, Any]:
    """Tokenize batched CoNLL words and align their integer BIO labels."""
    tokenized = tokenizer(
        examples["tokens"],
        truncation=True,
        max_length=max_length,
        is_split_into_words=True,
    )
    all_labels: list[list[int]] = []
    for index, labels in enumerate(examples["ner_tags"]):
        all_labels.append(align_ner_labels(tokenized.word_ids(index), labels))
    tokenized["labels"] = all_labels
    return tokenized
