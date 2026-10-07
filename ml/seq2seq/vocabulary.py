"""Frequency vocabulary for sequence-to-sequence text generation."""

from collections import Counter
from collections.abc import Iterable

from app.nlp.preprocessing import normalize_text, regex_tokenize

PAD_TOKEN = "<pad>"
UNK_TOKEN = "<unk>"
SOS_TOKEN = "<sos>"
EOS_TOKEN = "<eos>"
PAD_ID = 0
UNK_ID = 1
SOS_ID = 2
EOS_ID = 3
SPECIAL_TOKENS = (PAD_TOKEN, UNK_TOKEN, SOS_TOKEN, EOS_TOKEN)


def tokenize_seq2seq(text: str) -> list[str]:
    """Reuse the Step 8 normalized, Unicode-aware tokenizer."""
    return regex_tokenize(normalize_text(text))


class Seq2SeqVocabulary:
    """Map Step 8 normalized tokens to IDs with four reserved symbols."""

    def __init__(self, token_to_id: dict[str, int]) -> None:
        if any(
            token_to_id.get(token) != index
            for index, token in enumerate(SPECIAL_TOKENS)
        ):
            raise ValueError("Vocabulary must reserve <pad>, <unk>, <sos>, and <eos>.")
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
    ) -> "Seq2SeqVocabulary":
        """Build from the existing Step 8 tokenizer, reserving space for controls."""
        if min_frequency < 1 or (
            max_size is not None and max_size < len(SPECIAL_TOKENS)
        ):
            raise ValueError("Invalid vocabulary frequency or maximum size.")
        counts: Counter[str] = Counter()
        for text in texts:
            counts.update(
                token for token in tokenize_seq2seq(text) if token not in SPECIAL_TOKENS
            )
        tokens = [
            token
            for token, count in counts.most_common()
            if count >= min_frequency and token not in SPECIAL_TOKENS
        ]
        if max_size is not None:
            tokens = tokens[: max_size - len(SPECIAL_TOKENS)]
        mapping = {token: index for index, token in enumerate(SPECIAL_TOKENS)}
        mapping.update({token: index for index, token in enumerate(tokens, start=4)})
        return cls(mapping)

    def encode(
        self, text: str, max_length: int | None = None, *, add_boundaries: bool = False
    ) -> list[int]:
        """Encode with optional SOS/EOS markers and right truncation."""
        tokens = tokenize_seq2seq(text)
        if max_length is not None:
            if max_length < 1:
                raise ValueError("max_length must be positive.")
            tokens = tokens[:max_length]
        ids = [self.token_to_id.get(token, UNK_ID) for token in tokens]
        if not ids:
            ids = [UNK_ID]
        return [SOS_ID, *ids, EOS_ID] if add_boundaries else ids

    def decode(
        self,
        token_ids: Iterable[int],
        *,
        skip_special: bool = True,
        preserve_unk: bool = False,
    ) -> list[str]:
        """Convert IDs to tokens, stopping at EOS and optionally hiding controls."""
        tokens: list[str] = []
        for token_id in token_ids:
            if token_id < 0 or token_id >= len(self.id_to_token):
                token = UNK_TOKEN
            else:
                token = self.id_to_token[token_id]
            if token == EOS_TOKEN:
                break
            if (
                skip_special
                and token in SPECIAL_TOKENS
                and not (preserve_unk and token == UNK_TOKEN)
            ):
                continue
            tokens.append(token)
        return tokens

    def to_dict(self) -> dict[str, dict[str, int]]:
        return {"token_to_id": self.token_to_id}

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "Seq2SeqVocabulary":
        mapping = value.get("token_to_id")
        if not isinstance(mapping, dict) or not all(
            isinstance(token, str) and isinstance(index, int)
            for token, index in mapping.items()
        ):
            raise ValueError("Invalid serialized seq2seq vocabulary.")
        return cls(mapping)

    def __len__(self) -> int:
        return len(self.token_to_id)
