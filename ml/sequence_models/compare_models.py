"""Train and compare RNN, LSTM, GRU, and BiLSTM on one IMDB data split."""

import argparse
import csv
import gc
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import torch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for directory in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from ml.sequence_models.classification import train_classifier
from ml.sequence_models.data import load_imdb, read_config
from ml.sequence_models.models import Architecture
from ml.sequence_models.trainer import set_seed
from ml.sequence_models.vocabulary import Vocabulary

ARCHITECTURES: tuple[Architecture, ...] = ("rnn", "lstm", "gru", "bilstm")
RESULTS_DIR = PROJECT_ROOT / "docs" / "results"
FIGURES_DIR = RESULTS_DIR / "figures"


def _log_mlflow(result: dict[str, Any], config: dict[str, Any]) -> None:
    """Log an enabled run without making MLflow mandatory for local CSV/JSON output."""
    import mlflow

    with mlflow.start_run(run_name=f"sentiment-{result['architecture']}"):
        mlflow.log_params(
            {
                key: value
                for key, value in config.items()
                if isinstance(value, (str, int, float, bool))
            }
        )
        mlflow.log_param("architecture", result["architecture"])
        mlflow.log_metric("training_seconds", result["training_seconds"])
        mlflow.log_metric("parameter_count", result["parameter_count"])
        mlflow.log_metric("peak_vram_gib", result["peak_vram_gib"])
        mlflow.log_metric(
            "gpu_utilization_peak_percent",
            result["gpu_utilization_peak_percent"],
        )
        mlflow.log_param("effective_batch_size", result["batch_size"])
        mlflow.log_param("embedding_init", result["embedding_init"])
        for metric in ("accuracy", "precision", "recall", "macro_f1"):
            mlflow.log_metric(metric, result["metrics"][metric])


def _write_results(results: list[dict[str, Any]]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    serializable = [
        {key: value for key, value in result.items() if key != "vocabulary"}
        for result in results
    ]
    (RESULTS_DIR / "sequence_models.json").write_text(
        json.dumps(serializable, indent=2) + "\n",
        encoding="utf-8",
    )
    csv_path = RESULTS_DIR / "sequence_models.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "architecture",
                "accuracy",
                "precision",
                "recall",
                "macro_f1",
                "confusion_matrix",
                "training_seconds",
                "parameter_count",
                "peak_vram_gib",
                "gpu_utilization_peak_percent",
                "batch_size",
                "eval_batch_size",
                "embedding_init",
            ],
        )
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "architecture": result["architecture"],
                    **{
                        key: result["metrics"][key]
                        for key in (
                            "accuracy",
                            "precision",
                            "recall",
                            "macro_f1",
                            "confusion_matrix",
                        )
                    },
                    "training_seconds": result["training_seconds"],
                    "parameter_count": result["parameter_count"],
                    "peak_vram_gib": result["peak_vram_gib"],
                    "gpu_utilization_peak_percent": result[
                        "gpu_utilization_peak_percent"
                    ],
                    "batch_size": result["batch_size"],
                    "eval_batch_size": result["eval_batch_size"],
                    "embedding_init": result["embedding_init"],
                }
            )


def _write_report(results: list[dict[str, Any]], config: dict[str, Any]) -> None:
    lines = [
        "# Sequence model comparison",
        "",
        "## Updated run: longer sequences and larger batches",
        "",
        "Task: IMDB binary sentiment classification. All models use the same deterministic",
        (
            f"{config['train_samples']:,}-train / "
            f"{config['validation_samples']:,}-validation / "
            f"{config['test_samples']:,}-test subset and the same vocabulary."
        ),
        "Measurements below are from one local RTX 3050 run; they are not general benchmarks.",
        "",
        "| Model | Accuracy | Precision (macro) | Recall (macro) | Macro-F1 | Confusion matrix (actual × predicted) | Train time (s) | Parameters | Peak VRAM (GiB) | Peak GPU utilization (%) | Batch size | Embeddings |",
        "|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for result in results:
        metrics = result["metrics"]
        lines.append(
            f"| {result['architecture']} | {metrics['accuracy']:.4f} | "
            f"{metrics['precision']:.4f} | {metrics['recall']:.4f} | "
            f"{metrics['macro_f1']:.4f} | `{metrics['confusion_matrix']}` | "
            f"{result['training_seconds']:.1f} | {result['parameter_count']:,} | "
            f"{result['peak_vram_gib']:.3f} | "
            f"{result['gpu_utilization_peak_percent']:.0f} | "
            f"{result['batch_size']} | {result['embedding_init']} |"
        )
    lines.extend(
        [
            "",
            (
                f"Configuration: batch_size={config['batch_size']}, "
                f"grad_accumulation_steps={config['grad_accumulation_steps']}, "
                f"max_seq_len={config['max_seq_len']}, "
                f"hidden_size={config['hidden_size']}, "
                f"epochs_up_to={config['epochs']}, "
                f"early_stopping_patience={config['early_stopping_patience']}, "
                f"lr_scheduler={config['lr_scheduler']}, "
                f"mixed_precision={config['mixed_precision']}, "
                f"embedding_source={config.get('embedding_source', 'none')}."
            ),
            "",
            (
                "Device: cuda (NVIDIA GeForce RTX 3050 Laptop GPU). GPU utilization "
                "is sampled from nvidia-smi per epoch; peak VRAM is PyTorch's "
                "maximum allocated memory."
            ),
            "",
            "Updated-run loss curves:",
        ]
    )
    lines.extend(
        f"- [{result['architecture']}](./figures/{result['loss_figure']})"
        for result in results
    )
    best_accuracy = max(results, key=lambda result: result["metrics"]["accuracy"])
    lines.extend(
        [
            "",
            "## Previous baseline (preserved)",
            "",
            (
                "Original run: 10,000 train / 2,000 validation / 2,000 test, "
                "batch size 16, sequence length 128, three epochs. GPU "
                "utilization was not recorded."
            ),
            "",
            "| Model | Accuracy | Precision (macro) | Recall (macro) | Macro-F1 | Confusion matrix (actual × predicted) | Train time (s) | Parameters | Peak VRAM (GiB) |",
            "|---|---:|---:|---:|---:|---|---:|---:|---:|",
            "| rnn | 0.6215 | 0.6240 | 0.6232 | 0.6212 | `[[595, 440], [317, 648]]` | 32.6 | 1,288,450 | 0.053 |",
            "| lstm | 0.6875 | 0.7120 | 0.6810 | 0.6732 | `[[897, 138], [487, 478]]` | 33.9 | 1,313,410 | 0.054 |",
            "| gru | 0.7185 | 0.7383 | 0.7232 | 0.7151 | `[[609, 426], [137, 828]]` | 33.3 | 1,305,090 | 0.053 |",
            "| bilstm | 0.7360 | 0.7362 | 0.7348 | 0.7350 | `[[796, 239], [289, 676]]` | 51.3 | 1,346,818 | 0.063 |",
            "",
            "## Analysis",
            "",
            (
                f"On this test subset, {best_accuracy['architecture']} had the "
                f"highest accuracy ({best_accuracy['metrics']['accuracy']:.1%}) "
                f"and macro-F1 ({best_accuracy['metrics']['macro_f1']:.3f})."
            ),
            "",
            "A vanilla RNN repeatedly multiplies gradients through the recurrent transition;",
            "when those products are small, gradients vanish and early context is hard to learn.",
            "Large products can instead explode, so gradient clipping is used. LSTM gates and",
            "a cell state provide controlled paths for information and gradients; GRU combines",
            "update/reset gates in a simpler state. These mechanisms often help on long context,",
            "but they do not guarantee higher scores on this particular subset or seed.",
            "",
            "A BiLSTM reads each review in both directions and can use later as well as earlier",
            "words when classifying the whole review. That is useful for offline classification",
            "but is not causal and cannot directly serve next-token generation.",
            "",
            "Difficulty labels are generated from readability, term rarity, sentence length,",
            "and technical-term density. They are weak heuristics, not expert ground truth;",
            "scores on them measure agreement with those rules and must not be read as validated",
            "educational difficulty.",
            "",
            "The updated numeric table and per-epoch loss traces are also available in",
            "[sequence_models.json](./sequence_models.json) and",
            "[sequence_models.csv](./sequence_models.csv).",
        ]
    )
    (RESULTS_DIR / "sequence_models.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def run_comparison(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Run each architecture sequentially and release GPU allocations between jobs."""
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; refusing to train on CPU.")
    set_seed(int(config["seed"]))
    training, validation, testing = load_imdb(config)
    vocabulary = Vocabulary.build(
        training[0],
        min_frequency=int(config["min_frequency"]),
        max_size=int(config["vocab_size"]),
    )
    results: list[dict[str, Any]] = []
    for architecture in ARCHITECTURES:
        attempt_config = dict(config)
        while True:
            set_seed(int(config["seed"]))
            try:
                result = train_classifier(
                    "sentiment",
                    architecture,
                    training,
                    validation,
                    testing,
                    vocabulary,
                    attempt_config,
                )
                break
            except RuntimeError as error:
                if "out of memory" not in str(error).lower():
                    raise
                next_batch_size = int(attempt_config["batch_size"]) // 2
                if next_batch_size < 1:
                    raise
                print(
                    f"OOM for {architecture} at batch_size="
                    f"{attempt_config['batch_size']}; retrying with "
                    f"batch_size={next_batch_size}.",
                    flush=True,
                )
                del error
                gc.collect()
                torch.cuda.empty_cache()
                attempt_config["batch_size"] = next_batch_size
                attempt_config["eval_batch_size"] = min(
                    int(attempt_config["eval_batch_size"]), next_batch_size
                )
        loss_figure = f"{architecture}_loss_seq{attempt_config['max_seq_len']}.png"
        result["loss_figure"] = loss_figure
        FIGURES_DIR.mkdir(parents=True, exist_ok=True)
        figure, axis = plt.subplots(figsize=(7, 4))
        axis.plot(
            [row["epoch"] for row in result["history"]],
            [row["train_loss"] for row in result["history"]],
            label="train",
            marker="o",
        )
        axis.plot(
            [row["epoch"] for row in result["history"]],
            [row["validation_loss"] for row in result["history"]],
            label="validation",
            marker="o",
        )
        axis.set(
            xlabel="Epoch", ylabel="Cross-entropy loss", title=architecture.upper()
        )
        axis.legend()
        figure.tight_layout()
        figure.savefig(FIGURES_DIR / loss_figure, dpi=140)
        plt.close(figure)
        if config.get("mlflow", False):
            _log_mlflow(result, config)
        results.append(result)
        print(
            f"Finished {architecture}: accuracy={result['metrics']['accuracy']:.4f} "
            f"macro_f1={result['metrics']['macro_f1']:.4f} "
            f"batch_size={result['batch_size']} "
            f"gpu_utilization_peak_percent="
            f"{result['gpu_utilization_peak_percent']:.0f} "
            f"peak_vram_gib={result['peak_vram_gib']:.3f}",
            flush=True,
        )
        del result
        gc.collect()
        torch.cuda.empty_cache()
    _write_results(results)
    _write_report(results, config)
    print((RESULTS_DIR / "sequence_models.md").read_text(encoding="utf-8"))
    return results


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=PROJECT_ROOT / "configs/local_4gb.yaml"
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Regenerate the Markdown report from completed JSON results without training.",
    )
    arguments = parser.parse_args()
    config = read_config(arguments.config)
    if arguments.report_only:
        results_path = RESULTS_DIR / "sequence_models.json"
        results = json.loads(results_path.read_text(encoding="utf-8"))
        _write_report(results, config)
        print((RESULTS_DIR / "sequence_models.md").read_text(encoding="utf-8"))
        return
    run_comparison(config)


if __name__ == "__main__":
    main()
