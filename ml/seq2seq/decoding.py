"""Greedy and beam search with attention traces and repeated n-gram blocking."""

from dataclasses import dataclass
from typing import Literal

import torch
from torch.nn import functional as F

from ml.seq2seq.models import SequenceToSequence
from ml.seq2seq.vocabulary import EOS_ID, PAD_ID, SOS_ID


@dataclass
class DecodingResult:
    token_ids: list[int]
    log_probability: float
    attention: list[list[float]]


@dataclass
class _Beam:
    tokens: list[int]
    log_probability: float
    state: tuple[torch.Tensor, torch.Tensor]
    attention: list[list[float]]
    finished: bool = False


def _blocked_candidates(tokens: list[int], ngram_size: int) -> set[int]:
    if ngram_size < 2 or len(tokens) < ngram_size - 1:
        return set()
    prefix = tuple(tokens[-(ngram_size - 1) :])
    blocked: set[int] = set()
    for index in range(len(tokens) - ngram_size + 1):
        if tuple(tokens[index : index + ngram_size - 1]) == prefix:
            blocked.add(tokens[index + ngram_size - 1])
    return blocked


def _next_log_probabilities(
    logits: torch.Tensor, tokens: list[int], ngram_block: int
) -> torch.Tensor:
    log_probs = F.log_softmax(logits.float(), dim=-1)
    log_probs[PAD_ID] = -torch.inf
    log_probs[SOS_ID] = -torch.inf
    blocked = _blocked_candidates(tokens, ngram_block)
    if blocked:
        log_probs[list(blocked)] = -torch.inf
    return log_probs


@torch.inference_mode()
def greedy_search(
    model: SequenceToSequence,
    source: torch.Tensor,
    source_length: int,
    *,
    max_steps: int = 60,
    ngram_block: int = 3,
) -> DecodingResult:
    model.eval()
    use_amp = source.device.type == "cuda"
    with torch.autocast(
        device_type=source.device.type, dtype=torch.float16, enabled=use_amp
    ):
        memory, mask, state = model.encode(source, torch.tensor([source_length]))
    token = torch.tensor([SOS_ID], device=source.device)
    tokens: list[int] = []
    alignments: list[list[float]] = []
    score = 0.0
    for _ in range(max_steps):
        with torch.autocast(
            device_type=source.device.type, dtype=torch.float16, enabled=use_amp
        ):
            logits, state, weights = model.decode_step(token, state, memory, mask)
        log_probs = _next_log_probabilities(logits[0], tokens, ngram_block)
        if not torch.isfinite(log_probs).any():
            log_probs = F.log_softmax(logits[0].float(), dim=-1)
        token_id = int(log_probs.argmax())
        score += float(log_probs[token_id])
        if token_id == EOS_ID:
            break
        if weights is not None:
            alignments.append(weights[0].float().cpu().tolist())
        tokens.append(token_id)
        token = torch.tensor([token_id], device=source.device)
    return DecodingResult(tokens, score, alignments)


def _normalized_score(beam: _Beam, length_penalty: float) -> float:
    length = max(1, len(beam.tokens))
    return beam.log_probability / (((5 + length) / 6) ** length_penalty)


@torch.inference_mode()
def beam_search(
    model: SequenceToSequence,
    source: torch.Tensor,
    source_length: int,
    *,
    beam_width: int = 4,
    max_steps: int = 60,
    length_penalty: float = 0.0,
    ngram_block: int = 3,
) -> DecodingResult:
    if beam_width < 1 or max_steps < 1 or length_penalty < 0:
        raise ValueError(
            "Beam width/max steps must be positive; length penalty nonnegative."
        )
    model.eval()
    use_amp = source.device.type == "cuda"
    with torch.autocast(
        device_type=source.device.type, dtype=torch.float16, enabled=use_amp
    ):
        memory, mask, initial_state = model.encode(
            source, torch.tensor([source_length])
        )
    beams = [_Beam([], 0.0, initial_state, [])]
    completed: list[_Beam] = []
    for _ in range(max_steps):
        candidates: list[_Beam] = []
        for beam in beams:
            if beam.finished:
                completed.append(beam)
                continue
            previous = beam.tokens[-1] if beam.tokens else SOS_ID
            token = torch.tensor([previous], device=source.device)
            with torch.autocast(
                device_type=source.device.type, dtype=torch.float16, enabled=use_amp
            ):
                logits, next_state, weights = model.decode_step(
                    token, beam.state, memory, mask
                )
            log_probs = _next_log_probabilities(logits[0], beam.tokens, ngram_block)
            if not torch.isfinite(log_probs).any():
                log_probs = F.log_softmax(logits[0].float(), dim=-1)
            values, indices = torch.topk(log_probs, min(beam_width, log_probs.numel()))
            for value, index in zip(values.tolist(), indices.tolist(), strict=True):
                token_id = int(index)
                attention = beam.attention
                if weights is not None and token_id != EOS_ID:
                    attention = [*attention, weights[0].float().cpu().tolist()]
                next_tokens = (
                    beam.tokens if token_id == EOS_ID else [*beam.tokens, token_id]
                )
                candidate = _Beam(
                    next_tokens,
                    beam.log_probability + float(value),
                    (next_state[0].clone(), next_state[1].clone()),
                    attention,
                    token_id == EOS_ID,
                )
                if candidate.finished:
                    completed.append(candidate)
                else:
                    candidates.append(candidate)
        candidates.sort(
            key=lambda item: _normalized_score(item, length_penalty), reverse=True
        )
        beams = candidates[:beam_width]
        if not beams:
            break
    finalists = [*completed, *beams]
    best = max(finalists, key=lambda item: _normalized_score(item, length_penalty))
    return DecodingResult(best.tokens, best.log_probability, best.attention)


def decode(
    model: SequenceToSequence,
    source: torch.Tensor,
    source_length: int,
    strategy: Literal["greedy", "beam"],
    **kwargs: float,
) -> DecodingResult:
    if strategy == "greedy":
        return greedy_search(model, source, source_length, **kwargs)
    return beam_search(model, source, source_length, **kwargs)
