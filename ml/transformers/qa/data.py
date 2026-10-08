"""SQuAD feature preparation and span alignment."""

from typing import Any


def prepare_qa_features(
    examples: dict[str, list[Any]],
    tokenizer: Any,
    *,
    max_length: int = 384,
    doc_stride: int = 128,
    training: bool,
) -> dict[str, Any]:
    """Tokenize SQuAD contexts and align answer character spans to tokens."""
    encoded = tokenizer(
        examples["question"],
        examples["context"],
        truncation="only_second",
        max_length=max_length,
        stride=doc_stride,
        return_overflowing_tokens=True,
        return_offsets_mapping=True,
        padding="max_length",
    )
    sample_mapping = encoded.pop("overflow_to_sample_mapping")
    offset_mappings = encoded["offset_mapping"]
    start_positions: list[int] = []
    end_positions: list[int] = []
    cls_index = tokenizer.cls_token_id
    if cls_index is None:
        raise ValueError("The QA tokenizer must define a CLS token.")
    if not training:
        encoded["example_id"] = []
    for feature_index, offsets in enumerate(offset_mappings):
        sample_index = sample_mapping[feature_index]
        if not training:
            encoded["example_id"].append(examples["id"][sample_index])
        sequence_ids = encoded.sequence_ids(feature_index)
        if not training:
            offset_mappings[feature_index] = [
                offset if sequence_ids[index] == 1 else None
                for index, offset in enumerate(offsets)
            ]
        answer = examples["answers"][sample_index]
        if not answer["answer_start"]:
            start_positions.append(cls_index)
            end_positions.append(cls_index)
            continue
        answer_start = answer["answer_start"][0]
        answer_end = answer_start + len(answer["text"][0])
        context_tokens = [
            index for index, sequence_id in enumerate(sequence_ids) if sequence_id == 1
        ]
        if not context_tokens:
            start_positions.append(cls_index)
            end_positions.append(cls_index)
            continue
        first_context = context_tokens[0]
        last_context = context_tokens[-1]
        if (
            offsets[first_context][0] > answer_start
            or offsets[last_context][1] < answer_end
        ):
            start_positions.append(cls_index)
            end_positions.append(cls_index)
            continue
        start_token = first_context
        while start_token <= last_context and offsets[start_token][0] <= answer_start:
            start_token += 1
        start_token -= 1
        end_token = last_context
        while end_token >= first_context and offsets[end_token][1] >= answer_end:
            end_token -= 1
        end_token += 1
        start_positions.append(start_token)
        end_positions.append(end_token)
    encoded["start_positions"] = start_positions
    encoded["end_positions"] = end_positions
    return encoded
