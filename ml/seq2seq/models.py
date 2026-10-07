"""LSTM encoder-decoder architectures and soft attention mechanisms."""

from dataclasses import asdict, dataclass
from typing import Literal

import torch
from torch import nn
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence

AttentionKind = Literal["none", "bahdanau", "luong"]
LuongScore = Literal["dot", "general"]


@dataclass(frozen=True)
class Seq2SeqConfig:
    """Shape and attention settings persisted alongside each model."""

    vocab_size: int
    embedding_dim: int = 128
    hidden_size: int = 256
    num_layers: int = 1
    dropout: float = 0.2
    bidirectional: bool = True
    attention: AttentionKind = "bahdanau"
    luong_score: LuongScore = "general"
    max_source_length: int = 400
    max_target_length: int = 60
    coverage: bool = False

    def to_dict(self) -> dict[str, int | float | bool | str]:
        return asdict(self)


class SoftAttention(nn.Module):
    """Masked additive or Luong dot/general attention over encoder states."""

    def __init__(
        self,
        query_size: int,
        memory_size: int,
        kind: Literal["bahdanau", "luong"],
        score: LuongScore = "general",
    ) -> None:
        super().__init__()
        self.kind = kind
        self.score = score
        if kind == "bahdanau":
            self.query_projection = nn.Linear(query_size, memory_size, bias=False)
            self.memory_projection = nn.Linear(memory_size, memory_size, bias=False)
            self.energy = nn.Linear(memory_size, 1, bias=False)
        elif score == "general":
            self.query_projection = nn.Linear(query_size, memory_size, bias=False)
            self.memory_projection = nn.Identity()
        else:
            if query_size != memory_size:
                self.query_projection = nn.Linear(query_size, memory_size, bias=False)
            else:
                self.query_projection = nn.Identity()
            self.memory_projection = nn.Identity()

    def forward(
        self,
        query: torch.Tensor,
        memory: torch.Tensor,
        source_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if self.kind == "bahdanau":
            projected_query = self.query_projection(query).unsqueeze(1)
            projected_memory = self.memory_projection(memory)
            scores = self.energy(
                torch.tanh(projected_memory + projected_query)
            ).squeeze(-1)
        else:
            projected_query = self.query_projection(query).unsqueeze(2)
            scores = torch.bmm(self.memory_projection(memory), projected_query).squeeze(
                -1
            )
        scores = scores.masked_fill(~source_mask, torch.finfo(scores.dtype).min)
        weights = torch.softmax(scores.float(), dim=-1).to(memory.dtype)
        context = torch.bmm(weights.unsqueeze(1), memory).squeeze(1)
        return context, weights


class SequenceToSequence(nn.Module):
    """LSTM encoder-decoder with no attention, Bahdanau, or Luong attention."""

    def __init__(self, config: Seq2SeqConfig) -> None:
        super().__init__()
        if config.vocab_size < 4 or config.num_layers < 1:
            raise ValueError("The vocabulary and recurrent layer count are invalid.")
        if config.coverage:
            raise ValueError(
                "Coverage attention is not implemented; set coverage=False."
            )
        if config.attention not in {"none", "bahdanau", "luong"}:
            raise ValueError(f"Unsupported attention type: {config.attention}")
        if config.luong_score not in {"dot", "general"}:
            raise ValueError(f"Unsupported Luong score: {config.luong_score}")
        self.config = config
        directions = 2 if config.bidirectional else 1
        self.memory_size = config.hidden_size * directions
        self.embedding = nn.Embedding(
            config.vocab_size, config.embedding_dim, padding_idx=0
        )
        self.encoder = nn.LSTM(
            config.embedding_dim,
            config.hidden_size,
            num_layers=config.num_layers,
            batch_first=True,
            bidirectional=config.bidirectional,
            dropout=config.dropout if config.num_layers > 1 else 0.0,
        )
        self.bridge_h = nn.Linear(self.memory_size, config.hidden_size)
        self.bridge_c = nn.Linear(self.memory_size, config.hidden_size)
        self.decoder = nn.LSTM(
            config.embedding_dim,
            config.hidden_size,
            num_layers=config.num_layers,
            batch_first=True,
            dropout=config.dropout if config.num_layers > 1 else 0.0,
        )
        self.attention = (
            SoftAttention(
                config.hidden_size,
                self.memory_size,
                config.attention,
                config.luong_score,
            )
            if config.attention != "none"
            else None
        )
        output_size = (
            config.hidden_size + self.memory_size
            if self.attention
            else config.hidden_size
        )
        self.output_projection = nn.Linear(output_size, config.vocab_size)
        self.dropout = nn.Dropout(config.dropout)

    def encode(
        self, source: torch.Tensor, source_lengths: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, tuple[torch.Tensor, torch.Tensor]]:
        if (
            source.ndim != 2
            or source_lengths.ndim != 1
            or source.shape[0] != source_lengths.shape[0]
        ):
            raise ValueError(
                "source must be [batch, time] and lengths must be [batch]."
            )
        embedded = self.dropout(self.embedding(source))
        packed = pack_padded_sequence(
            embedded, source_lengths.cpu(), batch_first=True, enforce_sorted=False
        )
        packed_memory, (hidden, cell) = self.encoder(packed)
        memory, _ = pad_packed_sequence(
            packed_memory, batch_first=True, total_length=source.shape[1]
        )
        if self.config.bidirectional:
            hidden = self._merge_directions(hidden)
            cell = self._merge_directions(cell)
        initial_hidden = torch.tanh(self.bridge_h(hidden))
        initial_cell = torch.tanh(self.bridge_c(cell))
        positions = torch.arange(source.shape[1], device=source.device).unsqueeze(0)
        source_mask = positions < source_lengths.to(source.device).unsqueeze(1)
        return memory, source_mask, (initial_hidden, initial_cell)

    def _merge_directions(self, state: torch.Tensor) -> torch.Tensor:
        state = state.reshape(
            self.config.num_layers, 2, state.shape[1], self.config.hidden_size
        )
        return torch.cat((state[:, 0], state[:, 1]), dim=-1)

    def decode_step(
        self,
        token_ids: torch.Tensor,
        state: tuple[torch.Tensor, torch.Tensor],
        memory: torch.Tensor,
        source_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, tuple[torch.Tensor, torch.Tensor], torch.Tensor | None]:
        embedded = self.dropout(self.embedding(token_ids.reshape(-1, 1)))
        output, next_state = self.decoder(embedded, state)
        query = output[:, 0]
        if self.attention is None:
            attention_weights = None
            features = query
        else:
            context, attention_weights = self.attention(query, memory, source_mask)
            features = torch.cat((query, context), dim=-1)
        return (
            self.output_projection(self.dropout(features)),
            next_state,
            attention_weights,
        )

    def forward(
        self,
        source: torch.Tensor,
        source_lengths: torch.Tensor,
        decoder_input: torch.Tensor,
        *,
        teacher_forcing_ratio: float = 1.0,
        scheduled_sampling: bool = False,
    ) -> tuple[torch.Tensor, torch.Tensor | None]:
        if not 0.0 <= teacher_forcing_ratio <= 1.0:
            raise ValueError("teacher_forcing_ratio must be between zero and one.")
        memory, mask, state = self.encode(source, source_lengths)
        current = decoder_input[:, 0]
        logits: list[torch.Tensor] = []
        alignments: list[torch.Tensor] = []
        for position in range(decoder_input.shape[1]):
            step_logits, state, weights = self.decode_step(current, state, memory, mask)
            logits.append(step_logits)
            if weights is not None:
                alignments.append(weights)
            if position + 1 < decoder_input.shape[1]:
                if scheduled_sampling:
                    use_truth = (
                        torch.rand(source.shape[0], device=source.device)
                        < teacher_forcing_ratio
                    )
                    predicted = step_logits.argmax(dim=-1)
                    current = torch.where(
                        use_truth, decoder_input[:, position + 1], predicted
                    )
                elif teacher_forcing_ratio == 1.0:
                    current = decoder_input[:, position + 1]
                elif teacher_forcing_ratio == 0.0:
                    current = step_logits.argmax(dim=-1)
                else:
                    use_truth = (
                        torch.rand(source.shape[0], device=source.device)
                        < teacher_forcing_ratio
                    )
                    current = torch.where(
                        use_truth,
                        decoder_input[:, position + 1],
                        step_logits.argmax(dim=-1),
                    )
        attention = torch.stack(alignments, dim=1) if alignments else None
        return torch.stack(logits, dim=1), attention
