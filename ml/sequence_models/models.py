"""From-scratch recurrent sequence classifiers."""

from collections.abc import Mapping
from typing import Literal

import torch
from torch import nn
from torch.nn.utils.rnn import pack_padded_sequence

Architecture = Literal["rnn", "lstm", "gru", "bilstm"]


class SequenceClassifier(nn.Module):
    """Embedding plus a packed RNN, LSTM, GRU, or bidirectional LSTM classifier."""

    def __init__(
        self,
        vocab_size: int,
        num_classes: int,
        architecture: Architecture = "lstm",
        embedding_dim: int = 100,
        hidden_size: int = 64,
        num_layers: int = 1,
        dropout: float = 0.2,
        embedding_weights: torch.Tensor | None = None,
        freeze_embeddings: bool = False,
    ) -> None:
        super().__init__()
        if architecture not in {"rnn", "lstm", "gru", "bilstm"}:
            raise ValueError(f"Unsupported architecture: {architecture}")
        if min(vocab_size, num_classes, embedding_dim, hidden_size, num_layers) < 1:
            raise ValueError("Model dimensions must be positive.")
        if not 0 <= dropout < 1:
            raise ValueError("dropout must be in [0, 1).")
        self.architecture = architecture
        self.embedding = nn.Embedding(vocab_size, embedding_dim, padding_idx=0)
        if embedding_weights is not None:
            if tuple(embedding_weights.shape) != (vocab_size, embedding_dim):
                raise ValueError(
                    "Embedding weights must match the vocabulary and dimension."
                )
            with torch.no_grad():
                self.embedding.weight.copy_(embedding_weights)
        self.embedding.weight.requires_grad = not freeze_embeddings
        with torch.no_grad():
            self.embedding.weight[0].zero_()
        bidirectional = architecture == "bilstm"
        recurrent_type: type[nn.RNNBase]
        if architecture == "rnn":
            recurrent_type = nn.RNN
        elif architecture in {"lstm", "bilstm"}:
            recurrent_type = nn.LSTM
        else:
            recurrent_type = nn.GRU
        self.recurrent = recurrent_type(
            input_size=embedding_dim,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
            bidirectional=bidirectional,
        )
        self.dropout = nn.Dropout(dropout)
        self.output = nn.Linear(hidden_size * (2 if bidirectional else 1), num_classes)

    def forward(self, input_ids: torch.Tensor, lengths: torch.Tensor) -> torch.Tensor:
        """Classify padded token IDs without processing their trailing padding."""
        if input_ids.ndim != 2 or lengths.ndim != 1:
            raise ValueError("Expected batch-first IDs and one length per example.")
        packed = pack_padded_sequence(
            self.embedding(input_ids),
            lengths.detach().to(device="cpu"),
            batch_first=True,
            enforce_sorted=False,
        )
        _, hidden = self.recurrent(packed)
        hidden_state = hidden[0] if isinstance(hidden, tuple) else hidden
        if self.architecture == "bilstm":
            final_hidden = torch.cat((hidden_state[-2], hidden_state[-1]), dim=1)
        else:
            final_hidden = hidden_state[-1]
        return self.output(self.dropout(final_hidden))


def build_classifier(
    vocab_size: int,
    num_classes: int,
    architecture: Architecture,
    model_config: Mapping[str, object],
    embedding_weights: torch.Tensor | None = None,
) -> SequenceClassifier:
    """Construct a classifier from the shared model configuration."""
    return SequenceClassifier(
        vocab_size=vocab_size,
        num_classes=num_classes,
        architecture=architecture,
        embedding_dim=int(model_config.get("embedding_dim", 100)),
        hidden_size=int(model_config.get("hidden_size", 64)),
        num_layers=int(model_config.get("num_layers", 1)),
        dropout=float(model_config.get("dropout", 0.2)),
        embedding_weights=embedding_weights,
        freeze_embeddings=bool(model_config.get("freeze_embeddings", False)),
    )
