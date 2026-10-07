"""Unit tests for recurrent model utilities and shared training behavior."""

import subprocess
from pathlib import Path
from typing import Any

import pytest
import torch
from ml.sequence_models.generation import (
    CharacterLanguageModel,
    decode_autoregressive,
    decode_teacher_forced,
    free_running_loss,
    teacher_forced_loss,
)
from ml.sequence_models.metrics import classification_metrics, confusion_matrix
from ml.sequence_models.models import SequenceClassifier
from ml.sequence_models.trainer import (
    SequenceDataset,
    Trainer,
    query_gpu_telemetry,
    sequence_collate,
    set_seed,
    train_truncated_bptt_batch,
)
from ml.sequence_models.vocabulary import PAD_ID, UNK_ID, Vocabulary, pad_sequences
from torch.utils.data import DataLoader


def _examples() -> tuple[list[str], list[int]]:
    texts = ["excellent delightful story"] * 10 + ["awful boring story"] * 10
    labels = [1] * 10 + [0] * 10
    return texts, labels


def _loader(
    vocabulary: Vocabulary,
    texts: list[str],
    labels: list[int],
    batch_size: int = 10,
) -> DataLoader[Any]:
    dataset = SequenceDataset(texts, labels, vocabulary, max_seq_len=16)
    return DataLoader(dataset, batch_size=batch_size, collate_fn=sequence_collate)


def test_vocabulary_and_padding_keep_special_ids_and_lengths() -> None:
    vocabulary = Vocabulary.build(
        ["red blue red", "blue green"], min_frequency=2, max_size=10
    )
    assert vocabulary.token_to_id["<pad>"] == PAD_ID
    assert vocabulary.token_to_id["<unk>"] == UNK_ID
    assert vocabulary.encode("red missing") == [
        vocabulary.token_to_id["red"],
        UNK_ID,
    ]
    padded, lengths = pad_sequences([[2, 3], [4]])
    assert padded.tolist() == [[2, 3], [4, PAD_ID]]
    assert lengths.tolist() == [2, 1]
    assert (
        Vocabulary.from_dict(vocabulary.to_dict()).token_to_id == vocabulary.token_to_id
    )


@pytest.mark.parametrize("architecture", ["rnn", "lstm", "gru", "bilstm"])
def test_all_architectures_return_batch_class_logits(architecture: str) -> None:
    model = SequenceClassifier(
        vocab_size=20,
        num_classes=3,
        architecture=architecture,  # type: ignore[arg-type]
        embedding_dim=8,
        hidden_size=6,
    )
    output = model(
        torch.tensor([[2, 3, 0], [4, 5, 6]]),
        torch.tensor([2, 3]),
    )
    assert output.shape == (2, 3)


def test_padding_tokens_do_not_affect_packed_sequence_output() -> None:
    model = SequenceClassifier(
        12, 2, architecture="gru", embedding_dim=8, hidden_size=6
    ).eval()
    lengths = torch.tensor([2])
    first = model(torch.tensor([[2, 3, 0, 0]]), lengths)
    second = model(torch.tensor([[2, 3, 8, 9]]), lengths)
    assert torch.allclose(first, second)


def test_hand_computed_classification_metrics() -> None:
    metrics = classification_metrics([0, 0, 1, 1], [0, 1, 1, 1], 2)
    assert metrics["accuracy"] == pytest.approx(0.75)
    assert metrics["precision"] == pytest.approx((1.0 + 2 / 3) / 2)
    assert metrics["recall"] == pytest.approx((0.5 + 1.0) / 2)
    assert metrics["macro_f1"] == pytest.approx((2 / 3 + 0.8) / 2)
    assert metrics["confusion_matrix"] == [[1, 1], [0, 2]]
    assert confusion_matrix([1, 0, 1], [0, 0, 1], 2) == [[1, 0], [1, 1]]


def test_gpu_telemetry_parses_nvidia_smi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def completed_process(
        *_args: Any, **_kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["nvidia-smi"],
            returncode=0,
            stdout="37, 1024, 4096\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", completed_process)
    assert query_gpu_telemetry(0) == {
        "utilization_percent": 37,
        "memory_used_mib": 1024,
        "memory_total_mib": 4096,
    }


def test_tiny_dataset_overfits_near_perfectly(tmp_path: Path) -> None:
    set_seed(13)
    texts, labels = _examples()
    vocabulary = Vocabulary.build(texts, min_frequency=1)
    model = SequenceClassifier(
        len(vocabulary),
        2,
        architecture="lstm",
        embedding_dim=8,
        hidden_size=16,
        dropout=0.0,
    )
    config = {
        "learning_rate": 0.03,
        "batch_size": 20,
        "grad_accumulation_steps": 1,
        "gradient_clip_norm": 1.0,
        "early_stopping_patience": 30,
        "mixed_precision": False,
    }
    loader = _loader(vocabulary, texts, labels, batch_size=20)
    trainer = Trainer(
        model, config, tmp_path / "overfit.last.pt", device=torch.device("cpu")
    )
    trainer.fit(loader, loader, epochs=20)
    model.eval()
    ids, lengths, expected = next(iter(loader))
    ids = ids.to(trainer.device)
    expected = expected.to(trainer.device)
    with torch.inference_mode():
        accuracy = (model(ids, lengths).argmax(dim=1) == expected).float().mean()
    assert float(accuracy) >= 0.95


def test_checkpoint_resume_and_early_stopping(tmp_path: Path) -> None:
    texts, labels = _examples()
    vocabulary = Vocabulary.build(texts, min_frequency=1)
    loader = _loader(vocabulary, texts, labels)
    config = {
        "learning_rate": 0.0,
        "grad_accumulation_steps": 1,
        "gradient_clip_norm": 1.0,
        "early_stopping_patience": 1,
        "lr_patience": 1,
        "mixed_precision": False,
    }
    checkpoint = tmp_path / "resume.last.pt"
    first = Trainer(
        SequenceClassifier(len(vocabulary), 2, embedding_dim=8, hidden_size=8),
        config,
        checkpoint,
        device=torch.device("cpu"),
    )
    history = first.fit(loader, loader, epochs=5)
    assert len(history) == 2
    resumed = Trainer(
        SequenceClassifier(len(vocabulary), 2, embedding_dim=8, hidden_size=8),
        config,
        checkpoint,
        device=torch.device("cpu"),
    )
    resumed.resume()
    assert resumed.start_epoch == 2
    assert resumed.best_checkpoint_path.is_file()
    continued = resumed.fit(loader, loader, epochs=3)
    assert continued[0]["epoch"] == 3


def test_gradient_clipping_is_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    texts, labels = _examples()
    vocabulary = Vocabulary.build(texts, min_frequency=1)
    loader = _loader(vocabulary, texts, labels, batch_size=10)
    model = SequenceClassifier(len(vocabulary), 2, embedding_dim=8, hidden_size=8)
    trainer = Trainer(
        model,
        {
            "learning_rate": 0.01,
            "grad_accumulation_steps": 1,
            "gradient_clip_norm": 0.5,
            "mixed_precision": False,
        },
        tmp_path / "clip.last.pt",
        device=torch.device("cpu"),
    )
    calls: list[float] = []
    original = torch.nn.utils.clip_grad_norm_

    def record(parameters: Any, max_norm: float, *args: Any, **kwargs: Any) -> Any:
        calls.append(max_norm)
        return original(parameters, max_norm, *args, **kwargs)

    monkeypatch.setattr(torch.nn.utils, "clip_grad_norm_", record)
    trainer.fit(loader, loader, epochs=1)
    assert calls == [0.5, 0.5]


def test_simulated_cuda_oom_has_actionable_guidance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    texts, labels = _examples()
    vocabulary = Vocabulary.build(texts, min_frequency=1)
    loader = _loader(vocabulary, texts, labels)
    trainer = Trainer(
        SequenceClassifier(len(vocabulary), 2, embedding_dim=8, hidden_size=8),
        {"mixed_precision": False},
        tmp_path / "oom.last.pt",
        device=torch.device("cpu"),
    )
    monkeypatch.setattr(
        trainer,
        "_run_epoch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            torch.cuda.OutOfMemoryError("simulated")
        ),
    )
    with pytest.raises(RuntimeError, match="Reduce batch_size or max_seq_len"):
        trainer.fit(loader, loader, epochs=1)


def test_character_lstm_teacher_forcing_and_truncated_bptt() -> None:
    model = CharacterLanguageModel(vocabulary_size=5, embedding_dim=4, hidden_size=6)
    sequence = torch.tensor([[0, 1, 2, 3, 4, 0, 1, 2]])
    criterion = torch.nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    loss = train_truncated_bptt_batch(
        model,
        sequence[:, :-1],
        sequence[:, 1:],
        optimizer,
        criterion,
        chunk_length=3,
        mixed_precision=False,
    )
    assert loss > 0
    assert teacher_forced_loss(model, sequence, criterion) > 0
    assert free_running_loss(model, sequence, 3, criterion) > 0
    vocabulary = list("abcde")
    char_to_id = {character: index for index, character in enumerate(vocabulary)}
    teacher_sample = decode_teacher_forced(model, "ab", "cd", char_to_id, vocabulary)
    free_sample = decode_autoregressive(model, "ab", char_to_id, vocabulary, 4)
    assert len(teacher_sample) == 4
    assert len(free_sample) == 6


@pytest.mark.slow
@pytest.mark.skipif(not torch.cuda.is_available(), reason="requires CUDA")
def test_cuda_fp16_training_smoke(tmp_path: Path) -> None:
    texts, labels = _examples()
    vocabulary = Vocabulary.build(texts, min_frequency=1)
    loader = _loader(vocabulary, texts[:4], labels[:4], batch_size=4)
    trainer = Trainer(
        SequenceClassifier(len(vocabulary), 2, embedding_dim=8, hidden_size=8),
        {
            "learning_rate": 0.001,
            "grad_accumulation_steps": 1,
            "gradient_clip_norm": 1.0,
            "mixed_precision": True,
        },
        tmp_path / "cuda.last.pt",
        device=torch.device("cuda"),
    )
    history = trainer.fit(loader, loader, epochs=1)
    assert history[0]["peak_vram_gib"] > 0
