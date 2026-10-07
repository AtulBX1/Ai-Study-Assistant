"""Shape, training, decoding, and metric checks for classical seq2seq."""

import pytest
import torch
from ml.seq2seq.data import SummaryDataset, collate_summaries
from ml.seq2seq.decoding import beam_search, greedy_search
from ml.seq2seq.evaluation import compute_metrics, repeated_trigram_rate
from ml.seq2seq.models import Seq2SeqConfig, SequenceToSequence
from ml.seq2seq.training import train_variant
from ml.seq2seq.vocabulary import EOS_ID, PAD_ID, SOS_ID, Seq2SeqVocabulary


def _model(attention: str = "bahdanau") -> SequenceToSequence:
    return SequenceToSequence(
        Seq2SeqConfig(
            vocab_size=12,
            embedding_dim=8,
            hidden_size=10,
            dropout=0,
            attention=attention,  # type: ignore[arg-type]
            max_source_length=8,
            max_target_length=6,
        )
    )


@pytest.mark.parametrize(
    ("attention", "score"),
    [
        ("none", "general"),
        ("bahdanau", "general"),
        ("luong", "dot"),
        ("luong", "general"),
    ],
)
def test_model_shapes_mask_and_attention_normalization(
    attention: str, score: str
) -> None:
    model = SequenceToSequence(
        Seq2SeqConfig(
            vocab_size=12,
            embedding_dim=8,
            hidden_size=10,
            dropout=0,
            attention=attention,  # type: ignore[arg-type]
            luong_score=score,  # type: ignore[arg-type]
        )
    )
    source = torch.tensor([[4, 5, 6, 3], [7, 8, 0, 0]])
    lengths = torch.tensor([4, 2])
    decoder = torch.tensor([[2, 4, 5], [2, 7, 8]])
    logits, weights = model(source, lengths, decoder)
    assert logits.shape == (2, 3, 12)
    if attention == "none":
        assert weights is None
    else:
        assert weights is not None
        assert weights.shape == (2, 3, 4)
        torch.testing.assert_close(weights.sum(dim=-1), torch.ones(2, 3))
        assert torch.count_nonzero(weights[1, :, 2:]) == 0


def test_teacher_forcing_ratio_changes_subsequent_inputs() -> None:
    torch.manual_seed(2)
    model = _model()
    source = torch.tensor([[4, 5, 6, 3]])
    lengths = torch.tensor([4])
    decoder = torch.tensor([[2, 8, 9, 10]])
    forced, _ = model(source, lengths, decoder, teacher_forcing_ratio=1.0)
    free, _ = model(source, lengths, decoder, teacher_forcing_ratio=0.0)
    assert torch.equal(forced[:, 0], free[:, 0])
    assert not torch.allclose(forced[:, 1:], free[:, 1:])


def test_beam_search_fixture_and_ngram_blocking() -> None:
    torch.manual_seed(12)
    model = _model()
    source = torch.tensor([[4, 5, 6, EOS_ID]])
    greedy = greedy_search(model, source, 4, max_steps=4, ngram_block=0)
    beam = beam_search(
        model,
        source,
        4,
        beam_width=1,
        max_steps=4,
        length_penalty=0,
        ngram_block=0,
    )
    assert beam.log_probability >= greedy.log_probability - 1e-6
    assert len(beam.token_ids) <= 4
    assert len(beam.attention) == len(beam.token_ids)
    assert all(token_id not in {PAD_ID, SOS_ID} for token_id in beam.token_ids)
    assert len(_blocked_candidates_for_test([4, 5, 6, 4, 5], 3)) > 0


def _blocked_candidates_for_test(tokens: list[int], size: int) -> set[int]:
    from ml.seq2seq.decoding import _blocked_candidates

    return _blocked_candidates(tokens, size)


def test_vocab_boundaries_and_padding() -> None:
    vocabulary = Seq2SeqVocabulary.build(
        ["A small test", "A second test"], min_frequency=1
    )
    assert vocabulary.encode("a missing", add_boundaries=True)[0] == 2
    assert vocabulary.encode("a missing", add_boundaries=True)[-1] == EOS_ID
    assert vocabulary.encode("unseen")[0] == 1
    assert vocabulary.decode([1]) == []
    assert vocabulary.decode([1], preserve_unk=True) == ["<unk>"]
    examples = [
        {"article": "a small test", "highlights": "small test"},
        {"article": "a second test", "highlights": "second"},
    ]
    batch = collate_summaries(
        [
            SummaryDataset(examples, vocabulary, 8, 6)[0],
            SummaryDataset(examples, vocabulary, 8, 6)[1],
        ]
    )
    assert batch[0].shape[0] == 2
    assert batch[2].shape == batch[3].shape
    assert PAD_ID == 0


def test_checkpoint_resume(tmp_path) -> None:
    vocabulary = Seq2SeqVocabulary.build(
        ["the small cat", "a long dog", "cat sits", "dog runs"], min_frequency=1
    )
    train = [
        {"article": "the small cat", "highlights": "cat sits"},
        {"article": "a long dog", "highlights": "dog runs"},
    ]
    settings = {
        "seed": 4,
        "embedding_dim": 8,
        "hidden_size": 8,
        "num_layers": 1,
        "dropout": 0.0,
        "bidirectional": True,
        "luong_score": "general",
        "source_max_length": 8,
        "target_max_length": 6,
        "coverage": False,
        "batch_size": 2,
        "eval_batch_size": 2,
        "learning_rate": 0.001,
        "weight_decay": 0.0,
        "mixed_precision": False,
        "resume": False,
        "grad_accumulation_steps": 1,
        "max_seconds_per_variant": 30,
        "epochs": 1,
        "teacher_forcing_ratio": 1.0,
        "scheduled_sampling": False,
        "gradient_clip_norm": 1.0,
        "early_stopping_patience": 5,
        "mlflow": False,
    }
    _, history = train_variant(
        "bahdanau", train, train, vocabulary, settings, tmp_path, torch.device("cpu")
    )
    assert len(history) == 1
    settings["resume"] = True
    settings["epochs"] = 2
    _, resumed_history = train_variant(
        "bahdanau", train, train, vocabulary, settings, tmp_path, torch.device("cpu")
    )
    assert len(resumed_history) == 2
    assert (tmp_path / "bahdanau.pt").is_file()


def test_metrics_on_hand_checked_text() -> None:
    scores = compute_metrics(
        ["the cat sat on the mat", "a dog ran"],
        ["the cat sat on a mat", "a dog ran"],
    )
    assert scores["rouge1"] > 0.8
    assert scores["rougeL"] > 0.8
    assert scores["bleu"] > 50
    assert scores["average_summary_length"] == pytest.approx(4.5)
    assert repeated_trigram_rate("a b c a b c") == pytest.approx(0.25)


@pytest.mark.slow
@pytest.mark.gpu
def test_attention_sanity_task_has_anti_diagonal_alignment() -> None:
    from ml.seq2seq.sanity import run_sanity

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    results = run_sanity(steps=700, device=device)
    assert results["none"]["token_accuracy"] < 0.95
    assert results["bahdanau"]["token_accuracy"] >= 0.95
    assert results["luong"]["token_accuracy"] >= 0.95
    assert results["bahdanau"]["anti_diagonal_alignment"] >= 0.8
    assert results["luong"]["anti_diagonal_alignment"] >= 0.8
