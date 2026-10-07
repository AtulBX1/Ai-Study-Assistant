"""Character-level LSTM for teacher-forced and autoregressive decoding."""

from collections.abc import Sequence

import torch
from torch import nn


class CharacterLanguageModel(nn.Module):
    """A small character embedding, LSTM, and next-character projection."""

    def __init__(
        self,
        vocabulary_size: int,
        embedding_dim: int = 64,
        hidden_size: int = 128,
    ) -> None:
        super().__init__()
        self.embedding = nn.Embedding(vocabulary_size, embedding_dim)
        self.lstm = nn.LSTM(embedding_dim, hidden_size, batch_first=True)
        self.output = nn.Linear(hidden_size, vocabulary_size)

    def forward(
        self,
        input_ids: torch.Tensor,
        hidden: tuple[torch.Tensor, torch.Tensor] | None = None,
    ) -> tuple[torch.Tensor, tuple[torch.Tensor, torch.Tensor]]:
        output, state = self.lstm(self.embedding(input_ids), hidden)
        return self.output(output), state


def teacher_forced_loss(
    model: CharacterLanguageModel,
    sequence: torch.Tensor,
    criterion: nn.Module,
) -> float:
    """Score every next character using the true previous character as context."""
    model.eval()
    with torch.inference_mode():
        logits, _ = model(sequence[:, :-1])
        loss = criterion(
            logits.reshape(-1, logits.shape[-1]), sequence[:, 1:].reshape(-1)
        )
    return float(loss)


def free_running_loss(
    model: CharacterLanguageModel,
    sequence: torch.Tensor,
    prefix_length: int,
    criterion: nn.Module,
) -> float:
    """Score a continuation while feeding each predicted character back as input."""
    model.eval()
    with torch.inference_mode():
        context = sequence[:, :prefix_length]
        hidden = None
        for position in range(prefix_length - 1):
            _, hidden = model(context[:, position : position + 1], hidden)
        current = context[:, -1:]
        losses: list[torch.Tensor] = []
        for position in range(prefix_length, sequence.shape[1]):
            logits, hidden = model(current, hidden)
            expected = sequence[:, position]
            losses.append(criterion(logits[:, -1], expected))
            current = logits[:, -1].argmax(dim=-1, keepdim=True)
    return float(torch.stack(losses).mean()) if losses else 0.0


def decode_teacher_forced(
    model: CharacterLanguageModel,
    prefix: str,
    true_continuation: str,
    char_to_id: dict[str, int],
    id_to_char: Sequence[str],
) -> str:
    """Predict each continuation character with the actual preceding text at each step."""
    model.eval()
    output = ""
    context = prefix
    with torch.inference_mode():
        for true_character in true_continuation:
            ids = torch.tensor(
                [[char_to_id.get(char, 0) for char in context]],
                dtype=torch.long,
                device=next(model.parameters()).device,
            )
            logits, _ = model(ids)
            predicted_id = int(logits[0, -1].argmax())
            output += id_to_char[predicted_id]
            context += true_character
    return prefix + output


def decode_autoregressive(
    model: CharacterLanguageModel,
    prefix: str,
    char_to_id: dict[str, int],
    id_to_char: Sequence[str],
    num_chars: int,
) -> str:
    """Generate text by feeding each predicted character back into the LSTM."""
    model.eval()
    generated = prefix
    device = next(model.parameters()).device
    input_ids = torch.tensor(
        [[char_to_id.get(char, 0) for char in prefix]],
        dtype=torch.long,
        device=device,
    )
    with torch.inference_mode():
        logits, hidden = model(input_ids)
        next_id = int(logits[0, -1].argmax())
        for _ in range(num_chars):
            generated += id_to_char[next_id]
            current = torch.tensor([[next_id]], dtype=torch.long, device=device)
            logits, hidden = model(current, hidden)
            next_id = int(logits[0, -1].argmax())
    return generated
