"""Train, evaluate, and report the three classical CNN/DailyMail models."""

import argparse
import gc
import json
import logging
import random
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import torch
import yaml

from ml.seq2seq.data import load_cnn_dailymail
from ml.seq2seq.decoding import beam_search, greedy_search
from ml.seq2seq.evaluation import compute_metrics, repeated_trigram_rate
from ml.seq2seq.models import Seq2SeqConfig, SequenceToSequence
from ml.seq2seq.training import train_variant
from ml.seq2seq.vocabulary import EOS_ID, Seq2SeqVocabulary, tokenize_seq2seq

ROOT = Path(__file__).resolve().parents[2]
VARIANTS = ("none", "bahdanau", "luong")


def _load_settings(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        document = yaml.safe_load(stream)
    settings = document.get("seq2seq")
    if not isinstance(settings, dict):
        raise TypeError(f"{path} must contain a seq2seq mapping.")
    settings.setdefault("luong_score", "general")
    settings.setdefault("resume", False)
    return settings


def _evaluation(
    model: SequenceToSequence,
    vocabulary: Seq2SeqVocabulary,
    examples: list[dict[str, str]],
    settings: dict[str, Any],
    device: torch.device,
    variant: str,
    plots_dir: Path,
) -> tuple[dict[str, dict[str, float]], list[dict[str, str]]]:
    predictions: dict[str, list[str]] = {"greedy": [], "beam": []}
    references = [item["highlights"] for item in examples]
    examples_for_report: list[dict[str, str]] = []
    attention_rows: dict[str, list[list[float]]] = {}
    token_rows: dict[str, list[str]] = {}
    for index, example in enumerate(examples):
        all_source_tokens = tokenize_seq2seq(example["article"])
        source_tokens = all_source_tokens[: model.config.max_source_length - 1]
        source_ids = [vocabulary.token_to_id.get(token, 1) for token in source_tokens]
        source_ids.append(EOS_ID)
        source = torch.tensor([source_ids], dtype=torch.long, device=device)
        generated: dict[str, str] = {}
        for strategy in ("greedy", "beam"):
            options: dict[str, int | float] = {
                "max_steps": model.config.max_target_length,
                "ngram_block": int(settings["ngram_block"]),
            }
            if strategy == "beam":
                options.update(
                    beam_width=int(settings["beam_width"]),
                    length_penalty=float(settings["length_penalty"]),
                )
                result = beam_search(model, source, len(source_ids), **options)
            else:
                result = greedy_search(model, source, len(source_ids), **options)
            text = " ".join(vocabulary.decode(result.token_ids, preserve_unk=True))
            predictions[strategy].append(text)
            generated[strategy] = text
            if index == 0 and strategy == "beam":
                attention_rows[variant] = result.attention
                token_rows[variant] = vocabulary.decode(
                    result.token_ids, preserve_unk=True
                )
        if index < 12:
            source_excerpt = example["article"][:1000]
            source_excerpt_tokens = tokenize_seq2seq(source_excerpt)
            source_oov_tokens = sorted(
                {
                    token
                    for token in source_excerpt_tokens
                    if token not in vocabulary.token_to_id
                }
            )
            repetition_result = greedy_search(
                model,
                source,
                len(source_ids),
                max_steps=model.config.max_target_length,
                ngram_block=0,
            )
            repetition_summary = " ".join(
                vocabulary.decode(repetition_result.token_ids, preserve_unk=True)
            )
            examples_for_report.append(
                {
                    "source": example["article"],
                    "source_token_count": str(len(all_source_tokens)),
                    "source_token_limit": str(model.config.max_source_length - 1),
                    "source_oov_tokens": ", ".join(source_oov_tokens),
                    "summary_greedy": generated["greedy"],
                    "summary_beam": generated["beam"],
                    "summary_unblocked": repetition_summary,
                    "reference": example["highlights"],
                    "repeated_trigram_rate": str(
                        repeated_trigram_rate(generated["beam"])
                    ),
                    "unblocked_repeated_trigram_rate": str(
                        repeated_trigram_rate(repetition_summary)
                    ),
                }
            )
    scores = {
        strategy: compute_metrics(texts, references)
        for strategy, texts in predictions.items()
    }
    _save_attention_plot(
        plots_dir / f"attention_{variant}.png",
        examples[0]["article"],
        attention_rows.get(variant, []),
        token_rows.get(variant, []),
        has_attention=model.config.attention != "none",
    )
    return scores, examples_for_report


def _save_attention_plot(
    path: Path,
    source_text: str,
    attention: list[list[float]],
    generated_tokens: list[str],
    *,
    has_attention: bool,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(10, 6))
    if has_attention and attention:
        source_tokens = tokenize_seq2seq(source_text)[: min(40, len(attention[0]))]
        matrix = np.asarray(attention, dtype=float)[:, : len(source_tokens)].T
        axis.imshow(matrix, aspect="auto", interpolation="nearest", cmap="viridis")
        axis.set_yticks(range(len(source_tokens)), source_tokens, fontsize=7)
        axis.set_xticks(
            range(min(len(generated_tokens), matrix.shape[1])),
            generated_tokens[: matrix.shape[1]],
            rotation=70,
            ha="right",
            fontsize=7,
        )
        axis.set(xlabel="Generated token", ylabel="Source token")
        figure.colorbar(axis.images[0], ax=axis, label="Attention weight")
    else:
        axis.text(
            0.5, 0.5, "Baseline has no attention weights", ha="center", va="center"
        )
        axis.set_axis_off()
    axis.set_title(f"{path.stem}: source-to-summary alignment")
    figure.tight_layout()
    figure.savefig(path, dpi=140)
    plt.close(figure)


def _write_reports(
    results: dict[str, Any],
    examples: dict[str, list[dict[str, str]]],
    output_dir: Path,
    device_name: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "evaluation.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    lines = [
        "# Step 9: Classical seq2seq evaluation",
        "",
        (
            f"Device: {device_name}. Dataset: `{results['dataset_id']}` "
            f"config `{results['dataset_config']}`."
        ),
        (
            f"Subsets: train={results['subset_sizes']['train']}, "
            f"validation={results['subset_sizes']['validation']}, "
            f"test={results['subset_sizes']['test']}."
        ),
        "",
        (
            "Scores are corpus BLEU and mean example-level ROUGE F1 on the "
            "same held-out subset."
        ),
        "",
        (
            "| Model | Decode | ROUGE-1 | ROUGE-2 | ROUGE-L | BLEU | Avg. length | "
            "Repeated trigrams | Best val loss | Peak VRAM (GiB) | Tokens/s |"
        ),
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    avg_attention_rouge = []
    for variant in VARIANTS:
        record = results["models"][variant]
        for strategy in ("greedy", "beam"):
            score = record["metrics"][strategy]
            lines.append(
                f"| {variant} | {strategy} | {score['rouge1']:.4f} | "
                f"{score['rouge2']:.4f} | "
                f"{score['rougeL']:.4f} | {score['bleu']:.2f} | "
                f"{score['average_summary_length']:.1f} | "
                f"{score['repeated_trigram_rate']:.3f} | "
                f"{record['best_validation_loss']:.4f} | "
                f"{record['peak_vram_gb']:.2f} | "
                f"{record['tokens_per_second']:.1f} |"
            )
        if variant != "none":
            avg_attention_rouge.append(record["metrics"]["beam"]["rougeL"])
    baseline = results["models"]["none"]["metrics"]["beam"]["rougeL"]
    attention_average = sum(avg_attention_rouge) / max(1, len(avg_attention_rouge))
    lines.extend(
        [
            "",
            (
                f"Beam ROUGE-L attention gap (mean Bahdanau/Luong minus no-attention): "
                f"{attention_average - baseline:+.4f} "
                f"(attention mean {attention_average:.4f}, no-attention {baseline:.4f})."
            ),
            "",
            (
                "The baseline has no learned alignment matrix; its panel below "
                "explicitly marks that absence."
            ),
            "",
        ]
    )
    for variant in VARIANTS:
        sample = examples[variant][0]
        lines.extend(
            [
                f"## {variant} example",
                "",
                f"Beam summary: {sample['summary_beam'] or '[empty summary]'}",
                "",
                f"Reference: {sample['reference']}",
                "",
                f"Loss curve: [{variant}_loss.png](./{variant}_loss.png)",
                "",
                f"Attention plot: [attention_{variant}.png](./attention_{variant}.png)",
                "",
            ]
        )
    lines.extend(
        [
            "## Analysis",
            "",
            (
                "This is a small, capped classical-model run, not a pretrained summarizer. "
                "The metrics and examples above come from the held-out subset; low or "
                "negative attention gaps are reported without implying a guaranteed "
                "attention benefit. Truncation, vocabulary OOVs, exposure bias, and "
                "limited recurrent context constrain these results."
            ),
            "",
        ]
    )
    (output_dir / "seq2seq.md").write_text("\n".join(lines), encoding="utf-8")
    _write_limitations(examples, output_dir / "seq2seq_limitations.md")


def _write_limitations(examples: dict[str, list[dict[str, str]]], path: Path) -> None:
    all_examples = [item for variant in VARIANTS for item in examples[variant]]

    def low_source_overlap(item: dict[str, str]) -> bool:
        source_tokens = set(tokenize_seq2seq(item["source"]))
        summary_tokens = [
            token
            for token in tokenize_seq2seq(item["summary_beam"])
            if len(token) > 2
            and token
            not in {
                "the",
                "and",
                "for",
                "that",
                "with",
                "from",
                "this",
                "was",
                "were",
                "are",
                "has",
                "have",
                "had",
                "its",
                "his",
                "her",
                "their",
                "they",
                "them",
                "you",
                "your",
                "not",
                "but",
                "who",
                "what",
                "when",
                "where",
                "which",
                "will",
                "would",
                "could",
                "should",
                "about",
                "after",
                "before",
                "into",
                "than",
                "then",
                "there",
                "here",
                "been",
                "being",
                "says",
                "said",
            }
        ]
        return len(summary_tokens) >= 5 and (
            sum(token in source_tokens for token in summary_tokens)
            / len(summary_tokens)
            < 0.25
        )

    categories = [
        (
            "Repetition",
            lambda item: float(item.get("unblocked_repeated_trigram_rate", "0")) > 0,
            (
                "With trigram blocking disabled for this diagnostic decode, an earlier "
                "trigram repeats as model predictions become later context."
            ),
        ),
        (
            "Out-of-vocabulary token",
            lambda item: bool(item.get("source_oov_tokens")),
            (
                "The displayed source excerpt contains words absent from the training "
                "vocabulary; encoding maps each such word to <unk>."
            ),
        ),
        (
            "Long-range context",
            lambda item: (
                int(item.get("source_token_count", "0"))
                > int(item.get("source_token_limit", "0"))
            ),
            (
                "The article exceeds the configured recurrent input window; only the "
                "first source-token limit is encoded, so later evidence is unavailable."
            ),
        ),
        (
            "Unsupported or contradictory detail",
            low_source_overlap,
            (
                "This output has low lexical overlap with its source; inspect the "
                "source-summary pair for an unsupported or contradictory claim."
            ),
        ),
        (
            "Exposure bias",
            lambda item: (
                bool(item["summary_greedy"])
                and item["summary_greedy"] != item["reference"].lower()
            ),
            (
                "Once an early generated token differs from the reference prefix, later "
                "decoder steps condition on model outputs rather than gold tokens."
            ),
        ),
    ]
    chosen: list[tuple[str, dict[str, str], str]] = []
    used: set[int] = set()
    for label, condition, explanation in categories:
        match = next(
            (item for item in all_examples if id(item) not in used and condition(item)),
            None,
        )
        if match is not None:
            chosen.append((label, match, explanation))
            used.add(id(match))
    lines = [
        "# Step 9: Limitations of classical seq2seq",
        "",
        (
            "These examples are actual held-out CNN/DailyMail records and trained-model "
            "outputs. Interpret factual-support candidates against their source; they "
            "are not an automatic factuality benchmark."
        ),
        "",
    ]
    for index, (label, item, explanation) in enumerate(chosen, start=1):
        summary = (
            item["summary_unblocked"] if label == "Repetition" else item["summary_beam"]
        )
        lines.extend(
            [
                f"## {index}. {label}",
                "",
                f"Source excerpt: {item['source'][:1000]}",
                "",
                f"Generated summary: {summary}",
                "",
                f"Reference: {item['reference']}",
                "",
                *(
                    [
                        (
                            "Diagnostic greedy decode with trigram blocking disabled; "
                            f"repeated-trigram rate: "
                            f"{item['unblocked_repeated_trigram_rate']}."
                        ),
                        "",
                    ]
                    if label == "Repetition"
                    else []
                ),
                *(
                    [
                        (
                            "OOV words in this excerpt (each encoded as `<unk>`): "
                            f"{item['source_oov_tokens']}"
                        ),
                        "",
                    ]
                    if label == "Out-of-vocabulary token"
                    else []
                ),
                *(
                    [
                        (
                            "Source length: "
                            f"{item['source_token_count']} tokens; encoded input limit: "
                            f"{item['source_token_limit']} tokens."
                        ),
                        "",
                    ]
                    if label == "Long-range context"
                    else []
                ),
                f"Syllabus link: {explanation}",
                "",
            ]
        )
    if len(chosen) < 5:
        lines.extend(
            [
                "## Evidence coverage",
                "",
                (
                    f"Only {len(chosen)} distinct categories had a matching generated "
                    "example. No examples have been fabricated; evaluate additional "
                    "outputs before claiming five evidence-backed examples."
                ),
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def run(
    config_path: Path,
    models_dir: Path,
    results_dir: Path,
    *,
    train_variants: tuple[str, ...] = VARIANTS,
    resume_variants: tuple[str, ...] = (),
    resume_budget_seconds: int | None = None,
) -> dict[str, Any]:
    if not train_variants or set(train_variants) - set(VARIANTS):
        raise ValueError("Select at least one supported seq2seq variant to train.")
    if set(resume_variants) - set(train_variants):
        raise ValueError("Every resumed variant must also be selected for training.")
    settings = _load_settings(config_path)
    seed = int(settings["seed"])
    random.seed(seed)
    torch.manual_seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    device_name = torch.cuda.get_device_name(0) if device.type == "cuda" else "CPU"
    print(f"device: {device.type}", flush=True)
    print(f"GPU: {device_name}", flush=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
    logger = logging.getLogger("seq2seq.train")
    for variant in train_variants:
        print(
            f"training run: {variant}; device: {device.type}; GPU: {device_name}",
            flush=True,
        )
    cache_dir = (ROOT / settings["cache_dir"]).resolve()
    data = load_cnn_dailymail(
        cache_dir,
        train_samples=int(settings["train_samples"]),
        validation_samples=int(settings["validation_samples"]),
        test_samples=int(settings["test_samples"]),
        dataset_id=str(settings["dataset_id"]),
        dataset_config=str(settings["dataset_config"]),
    )
    vocabulary = Seq2SeqVocabulary.build(
        (text for row in data["train"] for text in (row["article"], row["highlights"])),
        min_frequency=int(settings["min_frequency"]),
        max_size=int(settings["vocab_size"]),
    )
    logger.info(
        "Loaded %s config=%s subsets=%s vocabulary=%d",
        settings["dataset_id"],
        settings["dataset_config"],
        {split: len(rows) for split, rows in data.items()},
        len(vocabulary),
    )
    evaluation_path = models_dir / "evaluation.json"
    if evaluation_path.is_file() and len(train_variants) < len(VARIANTS):
        results = json.loads(evaluation_path.read_text(encoding="utf-8"))
    else:
        results = {
            "dataset_id": settings["dataset_id"],
            "dataset_config": settings["dataset_config"],
            "device": device.type,
            "gpu": device_name,
            "subset_sizes": {split: len(rows) for split, rows in data.items()},
            "models": {},
        }
    results.update(
        {
            "dataset_id": settings["dataset_id"],
            "dataset_config": settings["dataset_config"],
            "device": device.type,
            "gpu": device_name,
            "subset_sizes": {split: len(rows) for split, rows in data.items()},
        }
    )
    samples: dict[str, list[dict[str, str]]] = {}
    results_dir.mkdir(parents=True, exist_ok=True)
    for variant in VARIANTS:
        started = time.monotonic()
        if variant in train_variants:
            print(
                f"device: {device.type}; GPU: {device_name}; starting {variant}",
                flush=True,
            )
            variant_settings = dict(settings)
            variant_settings["resume"] = variant in resume_variants or bool(
                settings["resume"]
            )
            if variant in resume_variants and resume_budget_seconds is not None:
                variant_settings["max_seconds_per_variant"] = resume_budget_seconds
            model, history = train_variant(
                variant,
                data["train"],
                data["validation"],
                vocabulary,
                variant_settings,
                models_dir,
                device,
            )
            training_seconds = time.monotonic() - started
        else:
            checkpoint_path = models_dir / f"{variant}.pt"
            if not checkpoint_path.is_file():
                raise FileNotFoundError(
                    f"No saved {variant} checkpoint is available for evaluation."
                )
            checkpoint = torch.load(
                checkpoint_path, map_location=device, weights_only=False
            )
            model = SequenceToSequence(Seq2SeqConfig(**checkpoint["config"])).to(device)
            model.load_state_dict(checkpoint["model"])
            model.eval()
            history = checkpoint["history"]
            training_seconds = float(
                results.get("models", {}).get(variant, {}).get("training_seconds", 0)
            )
        shutil.copy2(
            models_dir / f"{variant}_loss.png",
            results_dir / f"{variant}_loss.png",
        )
        metrics, variant_examples = _evaluation(
            model,
            vocabulary,
            data["test"],
            settings,
            device,
            variant,
            results_dir,
        )
        samples[variant] = variant_examples
        peak = max((row["peak_vram_gb"] for row in history), default=0.0)
        results["models"][variant] = {
            "metrics": metrics,
            "best_validation_loss": min(
                (row["validation_loss"] for row in history), default=float("nan")
            ),
            "tokens_per_second": max(
                (row["tokens_per_second"] for row in history), default=0.0
            ),
            "peak_vram_gb": peak,
            "training_seconds": training_seconds,
        }
        evaluation_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        del model
        gc.collect()
        if device.type == "cuda":
            torch.cuda.empty_cache()
    _write_reports(results, samples, results_dir, device_name)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=ROOT / "configs" / "local_4gb.yaml"
    )
    parser.add_argument("--models-dir", type=Path, default=ROOT / "models" / "seq2seq")
    parser.add_argument("--results-dir", type=Path, default=ROOT / "docs" / "results")
    parser.add_argument(
        "--variants",
        nargs="+",
        choices=VARIANTS,
        default=VARIANTS,
        help="Train only the selected variants; others use saved best checkpoints.",
    )
    parser.add_argument(
        "--resume-variants",
        nargs="*",
        choices=VARIANTS,
        default=(),
        help="Resume selected variants from their latest checkpoints.",
    )
    parser.add_argument(
        "--resume-budget-seconds",
        type=int,
        default=None,
        help="Remaining time budget for variants that already have a partial run.",
    )
    arguments = parser.parse_args()
    run(
        arguments.config,
        arguments.models_dir,
        arguments.results_dir,
        train_variants=tuple(arguments.variants),
        resume_variants=tuple(arguments.resume_variants),
        resume_budget_seconds=arguments.resume_budget_seconds,
    )


if __name__ == "__main__":
    main()
