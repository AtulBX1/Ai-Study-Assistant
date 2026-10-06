"""Text preprocessing and owner-scoped lab endpoint tests."""

from conftest import access_token_for
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Document, DocumentPage, User
from app.nlp.preprocessing import (
    MAX_INPUT_CHARS,
    detect_language,
    generate_ngrams,
    handle_oov,
    normalize_text,
    preprocess_text,
    regex_tokenize,
    stem_tokens,
    tokenize,
)


def test_normalization_expands_contractions_and_masks_private_values() -> None:
    output = normalize_text("DON'T! I'm at 42, https://example.com, or me@example.com.")

    assert output.startswith("do not! i am at <num> , <url> ,")
    assert "do not" in output
    assert "i am" in output
    assert "<num>" in output
    assert "<url>" in output
    assert "<email>" in output
    assert "example.com" not in output
    assert "me@" not in output


def test_tokenizers_preserve_hyphens_and_emoji_without_crashing() -> None:
    text = "Mixed-case state-of-the-art 🙂"
    output = tokenize(text)

    assert output["language"] == "en"
    assert output["regex"].count("-") == 4
    assert "🙂" in output["regex"]
    assert output["spacy"]
    assert regex_tokenize(text) == output["regex"]


def test_unicode_whitespace_and_case_are_normalized() -> None:
    assert normalize_text("  Cafe\u0301\tMIXED   Case ") == "café mixed case"


def test_stemmers_return_side_by_side_deterministic_results() -> None:
    tokens = ["studies", "running", "relational"]

    first = stem_tokens(tokens)

    assert first == stem_tokens(tokens)
    assert len(first["porter"]) == len(tokens)
    assert len(first["snowball"]) == len(tokens)


def test_oov_uses_unknown_token_and_character_fallback() -> None:
    assert handle_oov(["known", "unseen"], {"known"}) == [
        {
            "token": "known",
            "known": True,
            "unknown_token": None,
            "character_fallback": [],
        },
        {
            "token": "unseen",
            "known": False,
            "unknown_token": "<UNK>",
            "character_fallback": list("unseen"),
        },
    ]


def test_ngrams_return_frequency_counts_in_stable_order() -> None:
    result = generate_ngrams(["a", "b", "a", "b"])

    assert result == generate_ngrams(["a", "b", "a", "b"])
    assert result["frequencies"][1] == {"a": 2, "b": 2}
    assert result["frequencies"][2] == {"a b": 2, "b a": 1}
    assert result["frequencies"][3] == {"a b a": 1, "b a b": 1}


def test_empty_input_and_punctuation_only_text_are_safe() -> None:
    assert normalize_text("") == ""
    assert (
        preprocess_text("", ["tokenization", "vectorization"])["vectorization"][
            "top_terms"
        ]
        == []
    )
    punctuation = preprocess_text("... !!!", ["punctuation", "ngrams"])
    assert punctuation["punctuation"] == []
    assert punctuation["ngrams"]["frequencies"] == {1: {}, 2: {}, 3: {}}


def test_very_long_input_is_rejected_at_the_configured_limit() -> None:
    try:
        preprocess_text("x" * (MAX_INPUT_CHARS + 1), ["normalization"])
    except ValueError as error:
        assert "character limit" in str(error)
    else:
        raise AssertionError("Oversized input should be rejected.")


def test_hindi_and_punjabi_use_safe_unicode_whitespace_fallbacks() -> None:
    hindi = "यह हिंदी में एक वाक्य है।"
    punjabi = "ਇਹ ਪੰਜਾਬੀ ਵਿੱਚ ਇੱਕ ਵਾਕ ਹੈ।"

    assert detect_language(hindi) == "hi"
    assert detect_language(punjabi) == "pa"
    assert tokenize(hindi)["spacy"] == hindi.split()
    assert preprocess_text("पहला वाक्य। दूसरा वाक्य।", ["sentence_segmentation"])[
        "sentence_segmentation"
    ] == ["पहला वाक्य।", "दूसरा वाक्य।"]
    assert (
        preprocess_text(hindi, ["sentence_segmentation", "linguistic"])["linguistic"][
            "model_loaded"
        ]
        is False
    )


def test_all_requested_step_outputs_are_deterministic() -> None:
    text = "The NLP model processes text and creates useful features."
    steps = ["tokenization", "normalization", "stemming", "ngrams", "vectorization"]

    assert preprocess_text(text, steps) == preprocess_text(text, steps)


def test_preprocess_endpoint_requires_authentication(client: TestClient) -> None:
    response = client.post("/lab/preprocess", json={"text": "A test."})

    assert response.status_code == 401


def test_preprocess_endpoint_and_document_ownership(
    client: TestClient, db_session: Session
) -> None:
    owner = User(
        email="lab-owner@example.com",
        full_name="Lab Owner",
        password_hash="unused",
    )
    other = User(
        email="other-lab-owner@example.com",
        full_name="Other Owner",
        password_hash="unused",
    )
    db_session.add_all([owner, other])
    db_session.flush()
    document = Document(
        owner_id=owner.id,
        title="unit-one.pdf",
        status="ready",
        page_count=1,
    )
    db_session.add(document)
    db_session.flush()
    db_session.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text="Original NLP text.",
            cleaned_text="original nlp text.",
        )
    )
    db_session.commit()

    owner_headers = {"Authorization": f"Bearer {access_token_for(owner.id)}"}
    response = client.post(
        "/lab/preprocess",
        headers=owner_headers,
        json={"text": "I'm studying NLP.", "steps": ["normalization"]},
    )
    assert response.status_code == 200
    assert response.json()["steps"]["normalization"] == "i am studying nlp."

    page_response = client.post(
        "/lab/preprocess",
        headers=owner_headers,
        json={
            "document_id": document.id,
            "page_start": 1,
            "page_end": 1,
            "steps": ["normalization"],
        },
    )
    assert page_response.status_code == 200
    assert page_response.json()["pages"] == [1]
    assert page_response.json()["steps"]["normalization"] == "original nlp text."

    ngrams_response = client.get(
        f"/lab/ngrams?document_id={document.id}&n=2",
        headers=owner_headers,
    )
    assert ngrams_response.status_code == 200
    assert ngrams_response.json()["pages"][0]["frequencies"]["2"]["original nlp"] == 1

    terms_response = client.get(
        f"/lab/tfidf-terms?document_id={document.id}",
        headers=owner_headers,
    )
    assert terms_response.status_code == 200
    assert terms_response.json()["pages"][0]["terms"]

    for method in ("tfidf", "yake", "rake"):
        keyphrases_response = client.get(
            f"/lab/keyphrases?document_id={document.id}&method={method}",
            headers=owner_headers,
        )
        assert keyphrases_response.status_code == 200

    other_headers = {"Authorization": f"Bearer {access_token_for(other.id)}"}
    assert (
        client.get(
            f"/lab/ngrams?document_id={document.id}",
            headers=other_headers,
        ).status_code
        == 404
    )


def test_preprocess_endpoint_rejects_oversized_and_ambiguous_inputs(
    client: TestClient, db_session: Session
) -> None:
    owner = User(
        email="limit-owner@example.com",
        full_name="Limit Owner",
        password_hash="unused",
    )
    db_session.add(owner)
    db_session.commit()
    headers = {"Authorization": f"Bearer {access_token_for(owner.id)}"}

    too_large = client.post(
        "/lab/preprocess",
        headers=headers,
        json={"text": "x" * (MAX_INPUT_CHARS + 1)},
    )
    ambiguous = client.post(
        "/lab/preprocess",
        headers=headers,
        json={"text": "content", "document_id": 1},
    )

    assert too_large.status_code == 422
    assert ambiguous.status_code == 422


def test_preprocess_endpoint_returns_every_pipeline_step_by_default(
    client: TestClient, db_session: Session
) -> None:
    owner = User(
        email="all-steps-owner@example.com",
        full_name="All Steps Owner",
        password_hash="unused",
    )
    db_session.add(owner)
    db_session.commit()
    headers = {"Authorization": f"Bearer {access_token_for(owner.id)}"}

    response = client.post(
        "/lab/preprocess",
        headers=headers,
        json={"text": "A small test."},
    )
    repeated_response = client.post(
        "/lab/preprocess",
        headers=headers,
        json={"text": "A small test."},
    )

    assert response.status_code == 200
    assert "keywords" in response.json()["steps"]
    assert "linguistic" in response.json()["steps"]
    assert response.json()["steps"] == repeated_response.json()["steps"]
