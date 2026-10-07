"""Lazy loading and inference for saved local sequence classifiers."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import torch

from ml.sequence_models.data import CLASS_NAMES, MODEL_ROOT
from ml.sequence_models.models import build_classifier
from ml.sequence_models.vocabulary import Vocabulary, pad_sequences


class ModelNotTrainedError(FileNotFoundError):
    """The requested task/architecture has no saved trained weights."""


class SequencePredictor:
    """A lazily loaded inference model with calibrated softmax class probabilities."""

    def __init__(self, artifact_path: Path, device: torch.device | None = None) -> None:
        self.device = device or torch.device(
            "cuda" if torch.cuda.is_available() else "cpu"
        )
        payload: dict[str, Any] = torch.load(
            artifact_path,
            map_location=self.device,
            weights_only=True,
        )
        self.vocabulary = Vocabulary.from_dict(payload["vocabulary"])
        self.classes: list[str] = payload["classes"]
        self.max_seq_len = int(payload["max_seq_len"])
        self.config = payload["model_config"]
        self.model = build_classifier(
            len(self.vocabulary),
            len(self.classes),
            payload["architecture"],
            self.config,
        ).to(self.device)
        self.model.load_state_dict(payload["state_dict"])
        self.model.eval()

    def predict(self, text: str) -> dict[str, Any]:
        """Return the most likely class and the probability for every class."""
        ids, lengths = pad_sequences([self.vocabulary.encode(text, self.max_seq_len)])
        with torch.inference_mode():
            with torch.autocast(
                device_type=self.device.type,
                dtype=torch.float16,
                enabled=self.device.type == "cuda",
            ):
                logits = self.model(ids.to(self.device), lengths)
            probabilities = torch.softmax(logits.float(), dim=1)[0].cpu().tolist()
        index = int(torch.tensor(probabilities).argmax())
        return {
            "label": self.classes[index],
            "confidence": probabilities[index],
            "probabilities": dict(zip(self.classes, probabilities, strict=True)),
        }


@lru_cache(maxsize=8)
def _cached_predictor(
    task: str, architecture: str, model_root: Path
) -> SequencePredictor:
    artifact_path = model_root / task / f"{architecture}.pt"
    if not artifact_path.is_file():
        raise ModelNotTrainedError(
            f"No trained {architecture} weights are available for {task}."
        )
    return SequencePredictor(artifact_path)


def get_predictor(
    task: str, architecture: str, model_root: Path = MODEL_ROOT
) -> SequencePredictor:
    """Return one cached model; model construction happens on its first request."""
    if task not in CLASS_NAMES:
        raise ValueError(f"Unsupported task: {task}")
    if architecture not in {"rnn", "lstm", "gru", "bilstm"}:
        raise ValueError(f"Unsupported architecture: {architecture}")
    return _cached_predictor(task, architecture, model_root.resolve())
