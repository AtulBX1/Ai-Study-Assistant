"""Lazy, bounded local inference helpers for Unit V transformer labs."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import torch

ROOT = Path(__file__).resolve().parents[3]
MODEL_ROOT = ROOT / "models" / "transformers"
MAX_MODEL_INPUT_CHARS = 20_000
os_environ_ready = False


def _configure_huggingface() -> None:
    """Keep Hugging Face telemetry disabled without treating warnings as errors."""
    global os_environ_ready
    if not os_environ_ready:
        import os

        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        os_environ_ready = True


def _device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def clear_transformer_cache() -> None:
    """Unload cached transformer models and tokenizers for tests or updates."""
    _load_qa.cache_clear()
    _load_ner.cache_clear()
    _load_t5.cache_clear()
    _load_attention_model.cache_clear()
    _load_tokenizers.cache_clear()


@lru_cache(maxsize=1)
def _load_qa() -> tuple[Any, Any, torch.device]:
    _configure_huggingface()
    path = MODEL_ROOT / "qa"
    if not (path / "config.json").is_file():
        raise FileNotFoundError(
            f"Extractive QA weights are not trained yet. Expected {path}; "
            "run ml/transformers/qa/train.py first."
        )
    from transformers import AutoModelForQuestionAnswering, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
    model = AutoModelForQuestionAnswering.from_pretrained(
        path, local_files_only=True
    ).to(_device())
    model.eval()
    return model, tokenizer, _device()


@lru_cache(maxsize=1)
def _load_ner() -> tuple[Any, Any, torch.device]:
    _configure_huggingface()
    path = MODEL_ROOT / "ner"
    if not (path / "config.json").is_file():
        raise FileNotFoundError(
            f"NER weights are not trained yet. Expected {path}; "
            "run ml/transformers/ner/train.py first."
        )
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
    model = AutoModelForTokenClassification.from_pretrained(
        path, local_files_only=True
    ).to(_device())
    model.eval()
    return model, tokenizer, _device()


@lru_cache(maxsize=2)
def _load_t5(task: str) -> tuple[Any, Any, torch.device]:
    _configure_huggingface()
    if task not in {"summarization", "question-generation"}:
        raise ValueError(f"Unsupported T5 task: {task}.")
    path = MODEL_ROOT / f"t5-{task}"
    if not (path / "config.json").is_file():
        raise FileNotFoundError(
            f"T5 {task} weights are not trained yet. Expected {path}; "
            "run ml/transformers/t5/train.py first."
        )
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(path, local_files_only=True).to(
        _device()
    )
    model.eval()
    return model, tokenizer, _device()


@lru_cache(maxsize=1)
def _load_attention_model() -> tuple[Any, Any, torch.device]:
    _configure_huggingface()
    path = MODEL_ROOT / "qa"
    if not (path / "config.json").is_file():
        raise FileNotFoundError(
            f"DistilBERT weights are not available yet. Train the QA model first; "
            f"expected {path}."
        )
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
    model = AutoModel.from_pretrained(path, local_files_only=True).to(_device())
    model.eval()
    return model, tokenizer, _device()


@lru_cache(maxsize=1)
def _load_tokenizers() -> tuple[Any, Any, Any]:
    _configure_huggingface()
    cache_names = {
        "gpt2": "openai-community/gpt2",
        "wordpiece": "distilbert/distilbert-base-uncased",
        "sentencepiece": "google-t5/t5-small",
    }
    from transformers import AutoTokenizer

    try:
        return tuple(
            AutoTokenizer.from_pretrained(model_id, local_files_only=True)
            for model_id in cache_names.values()
        )
    except OSError as error:
        raise FileNotFoundError(
            "Tokenizer assets are not cached locally. Run "
            "ml/transformers/download_assets.py before using /lab/tokenizers."
        ) from error


def _autocast(device: torch.device):
    return torch.autocast(
        device_type="cuda",
        dtype=torch.float16,
        enabled=device.type == "cuda",
    )


def clear_gpu_memory() -> None:
    """Release cached CUDA allocations after a reported inference OOM."""
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def answer_chunk(
    question: str, context: str, confidence_threshold: float
) -> dict[str, Any]:
    """Extract the highest-scoring answer span and preserve its character offsets."""
    if not question.strip() or not context.strip():
        raise ValueError("Question and context must be non-empty.")
    if len(question) + len(context) > MAX_MODEL_INPUT_CHARS:
        raise ValueError(f"Model input exceeds {MAX_MODEL_INPUT_CHARS} characters.")
    model, tokenizer, device = _load_qa()
    encoded = tokenizer(
        question,
        context,
        return_tensors="pt",
        return_offsets_mapping=True,
        truncation="only_second",
        max_length=384,
    )
    offsets = encoded.pop("offset_mapping")[0].tolist()
    encoded = {key: value.to(device) for key, value in encoded.items()}
    with torch.inference_mode(), _autocast(device):
        output = model(**encoded)
    start_logits = output.start_logits[0]
    end_logits = output.end_logits[0]
    start_candidates = torch.argsort(start_logits, descending=True)[:20].tolist()
    end_candidates = torch.argsort(end_logits, descending=True)[:20].tolist()
    spans = [
        (float(start_logits[start] + end_logits[end]), start, end)
        for start in start_candidates
        for end in end_candidates
        if end >= start
        and end - start < 30
        and offsets[start] != [0, 0]
        and offsets[end] != [0, 0]
    ]
    if spans:
        _, start_index, end_index = max(spans)
    else:
        start_index = 0
        end_index = 0
    start_probability = torch.softmax(start_logits.float(), dim=0)[start_index]
    end_probability = torch.softmax(end_logits.float(), dim=0)[end_index]
    confidence = float((start_probability * end_probability).item())
    start_char, _ = offsets[start_index]
    _, end_char = offsets[end_index]
    answer = context[start_char:end_char]
    found = bool(answer.strip()) and confidence >= confidence_threshold
    return {
        "answer": answer if found else "no answer found",
        "confidence": round(confidence, 6),
        "start_offset": start_char if found else None,
        "end_offset": end_char if found else None,
        "found": found,
    }


def extract_entities(text: str) -> list[dict[str, Any]]:
    """Return entity text, BIO-merged label, and page-local character offsets."""
    if not text.strip():
        return []
    if len(text) > MAX_MODEL_INPUT_CHARS:
        raise ValueError(f"Model input exceeds {MAX_MODEL_INPUT_CHARS} characters.")
    model, tokenizer, device = _load_ner()
    encoded = tokenizer(
        text,
        return_offsets_mapping=True,
        return_tensors="pt",
        truncation=True,
        max_length=512,
    )
    offsets = encoded.pop("offset_mapping")[0].tolist()
    inputs = {key: value.to(device) for key, value in encoded.items()}
    with torch.inference_mode(), _autocast(device):
        predictions = model(**inputs).logits[0].argmax(dim=-1).tolist()
    labels = model.config.id2label
    entities: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
    for prediction, (start, end) in zip(predictions, offsets, strict=True):
        if end <= start:
            continue
        label = labels[int(prediction)]
        if label == "O":
            if active:
                entities.append(active)
                active = None
            continue
        prefix, _, entity_type = label.partition("-")
        if not entity_type:
            continue
        if prefix == "B" or active is None or active["label"] != entity_type:
            if active:
                entities.append(active)
            active = {"label": entity_type, "start_offset": start, "end_offset": end}
        else:
            active["end_offset"] = end
    if active:
        entities.append(active)
    for entity in entities:
        entity["text"] = text[entity["start_offset"] : entity["end_offset"]]
    return entities


def summarize_text(text: str, decoding: str) -> str:
    """Generate a bounded summary with greedy or width-three beam decoding."""
    if not text.strip():
        raise ValueError("Text must be non-empty.")
    if len(text) > MAX_MODEL_INPUT_CHARS:
        raise ValueError(f"Model input exceeds {MAX_MODEL_INPUT_CHARS} characters.")
    model, tokenizer, device = _load_t5("summarization")
    encoded = tokenizer(
        "summarize: " + text,
        return_tensors="pt",
        truncation=True,
        max_length=512,
    ).to(device)
    with torch.inference_mode(), _autocast(device):
        output = model.generate(
            **encoded,
            max_new_tokens=128,
            num_beams=3 if decoding == "beam" else 1,
            do_sample=False,
        )
    return tokenizer.decode(output[0], skip_special_tokens=True)


def generate_question(text: str, answer: str | None) -> str:
    """Generate one grounded question from context with an optional answer marker."""
    if not text.strip():
        raise ValueError("Text must be non-empty.")
    if len(text) > MAX_MODEL_INPUT_CHARS:
        raise ValueError(f"Model input exceeds {MAX_MODEL_INPUT_CHARS} characters.")
    model, tokenizer, device = _load_t5("question-generation")
    if answer is not None:
        if not answer.strip() or answer not in text:
            raise ValueError("answer must be a non-empty substring of the source text.")
        prompt = f"generate question: {text} <hl> {answer} <hl>"
    else:
        prompt = f"generate question: {text}"
    encoded = tokenizer(
        prompt, return_tensors="pt", truncation=True, max_length=512
    ).to(device)
    with torch.inference_mode(), _autocast(device):
        output = model.generate(
            **encoded,
            max_new_tokens=128,
            num_beams=3,
            do_sample=False,
        )
    return tokenizer.decode(output[0], skip_special_tokens=True)


def tokenizer_lab(text: str) -> dict[str, Any]:
    """Compare GPT-2 BPE, DistilBERT WordPiece, and T5 SentencePiece encodings."""
    if not text.strip():
        raise ValueError("Text must be non-empty.")
    if len(text) > 2_000:
        raise ValueError("Tokenizer input exceeds the 2,000-character limit.")
    gpt2, distilbert, t5 = _load_tokenizers()
    strategies = (
        (
            "gpt2_bpe",
            gpt2,
            "Byte-level BPE: rare spellings are decomposed to bytes without a "
            "word-level OOV token.",
            "Numbers split into frequent digit/byte merges; the tokenizer does "
            "not normalize them to one number token.",
            "Emoji are encoded as byte sequences, so valid Unicode emoji do not "
            "become an unknown token.",
        ),
        (
            "distilbert_wordpiece",
            distilbert,
            "Rare words split into ## continuation pieces; unsupported characters "
            "can become [UNK].",
            "Numbers usually split into digit and punctuation pieces according "
            "to the WordPiece vocabulary.",
            "Emoji absent from the vocabulary commonly map to [UNK].",
        ),
        (
            "t5_sentencepiece",
            t5,
            "Rare spellings split into SentencePiece subwords; unsupported "
            "sequences use the model's unknown token.",
            "Numbers split into SentencePiece units rather than being normalized "
            "to a single number token.",
            "Emoji may be a learned piece or fall back to the SentencePiece "
            "unknown token, depending on the vocabulary.",
        ),
    )
    output = {}
    for name, tokenizer, rare_words, numbers, emoji in strategies:
        encoded = tokenizer(
            text,
            add_special_tokens=True,
            truncation=True,
            max_length=256,
        )
        tokens = tokenizer.convert_ids_to_tokens(encoded["input_ids"])
        output[name] = {
            "tokens": tokens,
            "ids": encoded["input_ids"],
            "token_count": len(encoded["input_ids"]),
            "rare_oov": rare_words,
            "numbers": numbers,
            "emoji": emoji,
            "note": "The token list above shows the handling of this exact input.",
        }
    return output


def attention_weights(text: str) -> dict[str, Any]:
    """Return per-layer/head DistilBERT self-attention for a short sentence."""
    if not text.strip():
        raise ValueError("Text must be non-empty.")
    if len(text) > 1_000:
        raise ValueError("Attention input exceeds the 1,000-character limit.")
    model, tokenizer, device = _load_attention_model()
    encoded = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        max_length=128,
    )
    encoded = {key: value.to(device) for key, value in encoded.items()}
    tokens = tokenizer.convert_ids_to_tokens(encoded["input_ids"][0])
    with torch.inference_mode(), _autocast(device):
        output = model(**encoded, output_attentions=True)
    return {
        "tokens": tokens,
        "layers": [layer[0].float().cpu().tolist() for layer in output.attentions],
        "shape": [
            len(output.attentions),
            int(model.config.n_heads),
            len(tokens),
            len(tokens),
        ],
    }


def sinusoidal_encoding(length: int, dimension: int) -> list[list[float]]:
    """Compute the classic sinusoidal position encodings from Transformer."""
    if not 1 <= length <= 512 or not 1 <= dimension <= 1024:
        raise ValueError("length must be 1..512 and dimension must be 1..1024.")
    positions = torch.arange(length, dtype=torch.float64).unsqueeze(1)
    dimensions = torch.arange(dimension, dtype=torch.float64)
    rates = torch.exp(
        (2 * torch.floor(dimensions / 2) / dimension)
        * -torch.log(torch.tensor(10_000.0))
    )
    angles = positions * rates
    encoding = torch.where(
        (dimensions.to(torch.long) % 2).unsqueeze(0) == 0,
        torch.sin(angles),
        torch.cos(angles),
    )
    return encoding.tolist()
