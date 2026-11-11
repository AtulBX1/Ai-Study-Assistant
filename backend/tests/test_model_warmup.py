"""Model warm-up startup behavior tests without loading model weights."""

from types import SimpleNamespace

from app.services import model_warmup


def test_model_warmup_is_skippable(monkeypatch):
    monkeypatch.setattr(
        model_warmup,
        "get_settings",
        lambda: SimpleNamespace(skip_model_warmup=True),
    )

    def forbidden_thread(*_args, **_kwargs):
        raise AssertionError("Skipped warm-up created a background thread")

    monkeypatch.setattr(model_warmup.threading, "Thread", forbidden_thread)

    assert model_warmup.start_model_warmup() is None
