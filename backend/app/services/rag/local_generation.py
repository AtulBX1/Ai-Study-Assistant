"""Lazy, offline causal-LM playground helpers for the RAG lab."""

import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings

MAX_PROMPT_CHARS = 4_000
MAX_NEW_TOKENS = 64


@lru_cache(maxsize=2)
def _load_local_model(model_name: str, cache_root: str) -> tuple[Any, Any, Any]:
    """Load only cached DistilGPT-2/GPT-2 weights; never downloads from a hub."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    root = Path(cache_root).expanduser()
    local_path = root / f"models--{model_name.replace('/', '--')}"
    snapshots = local_path / "snapshots"
    candidates = sorted(snapshots.iterdir(), reverse=True) if snapshots.is_dir() else []
    model_path = next(
        (
            path
            for path in candidates
            if (path / "config.json").is_file()
            and any(
                (path / name).is_file()
                for name in ("model.safetensors", "pytorch_model.bin")
            )
        ),
        None,
    )
    if model_path is None:
        readable_name = model_name.rsplit("/", 1)[-1]
        raise FileNotFoundError(
            f"Local {readable_name} weights are not cached in {root}. "
            "Place the model and tokenizer files there to enable this offline lab."
        )
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(model_path, local_files_only=True)
    model.eval()
    return model, tokenizer, torch


def _logits_as_list(logits: Any) -> list[float]:
    values = logits[0, -1, :]
    if hasattr(values, "detach"):
        values = values.detach().float().cpu().tolist()
    return [float(value) for value in values]


def _token_ids(encoded: Any) -> list[int]:
    ids = encoded["input_ids"] if isinstance(encoded, dict) else encoded.input_ids
    if hasattr(ids, "detach"):
        ids = ids.detach().cpu().tolist()
    while ids and isinstance(ids[0], list):
        ids = ids[0]
    return [int(token_id) for token_id in ids]


def _probabilities(
    logits: list[float], setting: dict[str, Any], seen: list[int]
) -> list[float]:
    temperature = setting["temperature"]
    adjusted = [value / temperature for value in logits]
    penalty = setting["repetition_penalty"]
    if penalty != 1.0:
        for token_id in set(seen):
            if 0 <= token_id < len(adjusted):
                adjusted[token_id] = (
                    adjusted[token_id] / penalty
                    if adjusted[token_id] > 0
                    else adjusted[token_id] * penalty
                )
    strategy = setting["strategy"]
    if strategy == "top_k":
        keep = set(
            sorted(range(len(adjusted)), key=adjusted.__getitem__, reverse=True)[
                : setting["top_k"]
            ]
        )
        adjusted = [
            value if index in keep else -math.inf
            for index, value in enumerate(adjusted)
        ]
    elif strategy == "top_p":
        ordered = sorted(range(len(adjusted)), key=adjusted.__getitem__, reverse=True)
        maximum = max(adjusted)
        exp_values = [math.exp(value - maximum) for value in adjusted]
        denominator = sum(exp_values)
        kept: set[int] = set()
        cumulative = 0.0
        for index in ordered:
            kept.add(index)
            cumulative += exp_values[index] / denominator
            if cumulative >= setting["top_p"]:
                break
        adjusted = [
            value if index in kept else -math.inf
            for index, value in enumerate(adjusted)
        ]
    maximum = max(adjusted)
    exp_values = [
        math.exp(value - maximum) if math.isfinite(value) else 0.0 for value in adjusted
    ]
    denominator = sum(exp_values)
    return [value / denominator for value in exp_values]


def _choose(
    model: Any,
    tokenizer: Any,
    torch: Any,
    prompt: str,
    setting: dict[str, Any],
    generated: list[int],
) -> tuple[int, float]:
    text = prompt + tokenizer.decode(generated, skip_special_tokens=True)
    encoded = tokenizer(text, return_tensors="pt")
    inputs = encoded["input_ids"] if isinstance(encoded, dict) else encoded.input_ids
    with torch.inference_mode():
        logits = model(input_ids=inputs).logits
    probabilities = _probabilities(_logits_as_list(logits), setting, generated)
    if setting["strategy"] in {"greedy", "beam"}:
        selected = max(range(len(probabilities)), key=probabilities.__getitem__)
    else:
        selected = int(
            torch.multinomial(torch.tensor(probabilities), num_samples=1).item()
        )
    return selected, probabilities[selected]


def _generate_setting(
    model: Any, tokenizer: Any, torch: Any, prompt: str, setting: dict[str, Any]
) -> dict[str, Any]:
    strategy = setting["strategy"]
    if strategy != "beam":
        generated: list[int] = []
        token_probs: list[dict[str, Any]] = []
        for _ in range(setting["max_new_tokens"]):
            token_id, probability = _choose(
                model, tokenizer, torch, prompt, setting, generated
            )
            generated.append(token_id)
            token_probs.append(
                {
                    "token": tokenizer.decode([token_id], skip_special_tokens=True),
                    "token_id": token_id,
                    "probability": round(probability, 8),
                }
            )
            if token_id == tokenizer.eos_token_id:
                break
    else:
        beams: list[tuple[list[int], float, list[dict[str, Any]]]] = [([], 0.0, [])]
        beam_width = setting["num_beams"]
        for _ in range(setting["max_new_tokens"]):
            candidates: list[tuple[list[int], float, list[dict[str, Any]]]] = []
            for generated, score, token_probs in beams:
                if generated and generated[-1] == tokenizer.eos_token_id:
                    candidates.append((generated, score, token_probs))
                    continue
                text = prompt + tokenizer.decode(generated, skip_special_tokens=True)
                encoded = tokenizer(text, return_tensors="pt")
                inputs = (
                    encoded["input_ids"]
                    if isinstance(encoded, dict)
                    else encoded.input_ids
                )
                with torch.inference_mode():
                    logits = model(input_ids=inputs).logits
                probabilities = _probabilities(
                    _logits_as_list(logits), setting, generated
                )
                top_ids = sorted(
                    range(len(probabilities)),
                    key=probabilities.__getitem__,
                    reverse=True,
                )[:beam_width]
                for token_id in top_ids:
                    probability = probabilities[token_id]
                    item = {
                        "token": tokenizer.decode([token_id], skip_special_tokens=True),
                        "token_id": token_id,
                        "probability": round(probability, 8),
                    }
                    candidates.append(
                        (
                            generated + [token_id],
                            score + math.log(max(probability, 1e-30)),
                            [*token_probs, item],
                        )
                    )
            beams = sorted(candidates, key=lambda item: item[1], reverse=True)[
                :beam_width
            ]
            if beams and all(
                tokens and tokens[-1] == tokenizer.eos_token_id
                for tokens, _, _ in beams
            ):
                break
        generated, _, token_probs = beams[0]
    return {
        "setting": setting,
        "text": tokenizer.decode(generated, skip_special_tokens=True),
        "tokens": token_probs,
    }


def generate_side_by_side(
    prompt: str,
    settings: list[dict[str, Any]],
    runtime_settings: Settings | None = None,
) -> dict[str, Any]:
    """Generate reproducible outputs and selected-token probabilities per setting."""
    if not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(
            f"Prompt must be non-empty and at most {MAX_PROMPT_CHARS} characters."
        )
    config = runtime_settings or get_settings()
    model_name = (
        "distilgpt2"
        if config.rag_playground_model == "distilgpt2"
        else "openai-community/gpt2"
    )
    model, tokenizer, torch = _load_local_model(model_name, config.hf_home)
    return {
        "model": config.rag_playground_model,
        "results": [
            _generate_setting(model, tokenizer, torch, prompt, setting)
            for setting in settings
        ],
    }


def calculate_perplexity(
    text: str, runtime_settings: Settings | None = None
) -> dict[str, Any]:
    """Compute causal next-token perplexity locally for a bounded text sample."""
    if not text.strip() or len(text) > MAX_PROMPT_CHARS:
        raise ValueError(
            f"Text must be non-empty and at most {MAX_PROMPT_CHARS} characters."
        )
    config = runtime_settings or get_settings()
    model_name = (
        "distilgpt2"
        if config.rag_playground_model == "distilgpt2"
        else "openai-community/gpt2"
    )
    model, tokenizer, torch = _load_local_model(model_name, config.hf_home)
    encoded = tokenizer(text, return_tensors="pt")
    ids = _token_ids(encoded)
    if len(ids) < 2:
        raise ValueError("Perplexity requires at least two tokens.")
    inputs = encoded["input_ids"] if isinstance(encoded, dict) else encoded.input_ids
    with torch.inference_mode():
        logits = model(input_ids=inputs).logits
    total_loss = 0.0
    for index in range(1, len(ids)):
        values = logits[0, index - 1, :]
        if hasattr(values, "detach"):
            values = values.detach().float().cpu().tolist()
        scores = [float(value) for value in values]
        maximum = max(scores)
        log_partition = maximum + math.log(
            sum(math.exp(value - maximum) for value in scores)
        )
        total_loss += log_partition - scores[ids[index]]
    mean_loss = total_loss / (len(ids) - 1)
    return {
        "model": config.rag_playground_model,
        "token_count": len(ids),
        "perplexity": round(math.exp(min(mean_loss, 50)), 6),
    }
