"""Lazy inference loader for locally trained seq2seq summarization models."""

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import torch

ROOT = Path(__file__).resolve().parents[3]
MODEL_VARIANTS = ("none", "bahdanau", "luong")


def _project_imports() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


@lru_cache(maxsize=3)
def _load_model(
    variant: Literal["none", "bahdanau", "luong"],
) -> tuple[Any, Any, torch.device]:
    _project_imports()
    from ml.seq2seq.models import Seq2SeqConfig, SequenceToSequence
    from ml.seq2seq.vocabulary import Seq2SeqVocabulary

    checkpoint_path = ROOT / "models" / "seq2seq" / f"{variant}.pt"
    if not checkpoint_path.is_file():
        raise FileNotFoundError(
            f"No trained {variant} seq2seq weights are available at "
            f"{checkpoint_path}. Train Step 9 models first."
        )
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    config = Seq2SeqConfig(**checkpoint["config"])
    vocabulary = Seq2SeqVocabulary.from_dict(checkpoint["vocabulary"])
    model = SequenceToSequence(config).to(device)
    model.load_state_dict(checkpoint["model"])
    model.eval()
    return model, vocabulary, device


def clear_model_cache() -> None:
    """Clear lazy-loaded weights, useful when replacing local checkpoints."""
    _load_model.cache_clear()


def summarize(
    text: str,
    variant: Literal["none", "bahdanau", "luong"],
    decoding: Literal["greedy", "beam"],
    beam_width: int = 4,
) -> dict[str, Any]:
    _project_imports()
    from ml.seq2seq.decoding import beam_search, greedy_search
    from ml.seq2seq.vocabulary import EOS_ID, tokenize_seq2seq

    model, vocabulary, device = _load_model(variant)
    source_tokens = tokenize_seq2seq(text)[: model.config.max_source_length - 1]
    if not source_tokens:
        raise ValueError("Text must contain at least one token.")
    source_ids = [vocabulary.token_to_id.get(token, 1) for token in source_tokens]
    source_ids.append(EOS_ID)
    source = torch.tensor([source_ids], dtype=torch.long, device=device)
    if decoding == "beam":
        result = beam_search(
            model,
            source,
            len(source_ids),
            beam_width=beam_width,
            max_steps=model.config.max_target_length,
            length_penalty=0.6,
            ngram_block=3,
        )
    else:
        result = greedy_search(
            model,
            source,
            len(source_ids),
            max_steps=model.config.max_target_length,
            ngram_block=3,
        )
    generated_tokens = vocabulary.decode(result.token_ids, preserve_unk=True)
    attention = result.attention
    truncated_source = source_tokens[:120]
    matrix = (
        [
            [
                round(float(attention[column][row]), 6)
                for column in range(len(attention))
            ]
            for row in range(min(120, len(truncated_source)))
        ]
        if attention
        else None
    )
    return {
        "model": variant,
        "decoding": decoding,
        "summary": " ".join(generated_tokens),
        "source_tokens": truncated_source,
        "generated_tokens": generated_tokens,
        "attention_matrix": matrix,
    }
