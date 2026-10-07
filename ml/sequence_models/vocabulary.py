"""Vocabulary and padding helpers using the Step 4 text preprocessing."""

from collections import Counter
from collections.abc import Iterable, Sequence

import torch
from app.nlp.preprocessing import normalize_text, regex_tokenize
from torch.nn.utils.rnn import pad_sequence

PAD_TOKEN = "<pad>"
UNK_TOKEN = "<unk>"
PAD_ID = 0
UNK_ID = 1


class Vocabulary:
    """Map normalized Step 4 tokens to stable integer IDs."""

    def __init__(self, token_to_id: dict[str, int]) -> None:
        if token_to_id.get(PAD_TOKEN) != PAD_ID or token_to_id.get(UNK_TOKEN) != UNK_ID:
            raise ValueError("Vocabulary must reserve <pad>=0 and <unk>=1.")
        self.token_to_id = token_to_id
        self.id_to_token = [
            token for token, _ in sorted(token_to_id.items(), key=lambda item: item[1])
        ]

    @classmethod
    def build(
        cls,
        texts: Iterable[str],
        min_frequency: int = 2,
        max_size: int | None = 20_000,
    ) -> "Vocabulary":
        """Build a frequency-ordered vocabulary with explicit padding and unknown IDs."""
        if min_frequency < 1 or (max_size is not None and max_size < 2):
            raise ValueError("min_frequency must be positive and max_size at least 2.")
        counts: Counter[str] = Counter()
        for text in texts:
            counts.update(token.lower() for token in tokenize_text(text))
        items = [
            (token, count)
            for token, count in counts.most_common()
            if count >= min_frequency and token not in {PAD_TOKEN, UNK_TOKEN}
        ]
        if max_size is not None:
            items = items[: max_size - 2]
        token_to_id = {PAD_TOKEN: PAD_ID, UNK_TOKEN: UNK_ID}
        token_to_id.update(
            {token: index for index, (token, _) in enumerate(items, start=2)}
        )
        return cls(token_to_id)

    def encode(self, text: str, max_seq_len: int | None = None) -> list[int]:
        """Encode normalized tokens, truncating from the right when requested."""
        tokens = tokenize_text(text)
        if max_seq_len is not None:
            if max_seq_len < 1:
                raise ValueError("max_seq_len must be at least 1.")
            tokens = tokens[:max_seq_len]
        return [self.token_to_id.get(token.lower(), UNK_ID) for token in tokens] or [
            UNK_ID
        ]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable vocabulary representation."""
        return {"token_to_id": self.token_to_id}

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "Vocabulary":
        """Restore a vocabulary saved by :meth:`to_dict`."""
        token_to_id = value.get("token_to_id")
        if not isinstance(token_to_id, dict) or not all(
            isinstance(token, str) and isinstance(index, int)
            for token, index in token_to_id.items()
        ):
            raise ValueError("Invalid serialized vocabulary.")
        return cls(token_to_id)

    def __len__(self) -> int:
        return len(self.token_to_id)


def tokenize_text(text: str) -> list[str]:
    """Apply the project's Step 4 normalization and Unicode-aware tokenizer."""
    return regex_tokenize(normalize_text(text))


def pad_sequences(
    sequences: Sequence[Sequence[int]],
    padding_value: int = PAD_ID,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Pad ID sequences batch-first and return CPU lengths for packed RNN input."""
    if not sequences:
        raise ValueError("At least one sequence is required.")
    tensors = [
        torch.tensor(sequence or [UNK_ID], dtype=torch.long) for sequence in sequences
    ]
    lengths = torch.tensor([len(sequence) for sequence in tensors], dtype=torch.long)
    padded = pad_sequence(
        tensors,
        batch_first=True,
        padding_value=padding_value,
    )
    return padded, lengths
