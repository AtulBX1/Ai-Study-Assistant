"""Run one transformer training job with a hard timeout and a persistent log."""

import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import torch
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _job_settings(config_path: Path, mode: str) -> dict[str, Any]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    transformer_config = config["transformers"]
    key = "summarization" if mode == "summarization" else mode
    return transformer_config[key]


def run(mode: str, config_path: Path) -> int:
    """Start one child training process, capture output, and enforce its limit."""
    device = "cuda" if torch.cuda.is_available() else "cpu"
    gpu_name = torch.cuda.get_device_name(0) if device == "cuda" else "CPU"
    settings = _job_settings(config_path, mode)
    max_seconds = int(settings["max_seconds"])
    module = {
        "qa": "ml.transformers.qa.train",
        "ner": "ml.transformers.ner.train",
        "summarization": "ml.transformers.t5.train",
        "question_generation": "ml.transformers.t5.train",
    }[mode]
    command = [sys.executable, "-u", "-m", module]
    if mode in {"summarization", "question_generation"}:
        command.append(mode)
    command.extend(["--config", str(config_path.resolve())])
    log_dir = ROOT / "models" / "transformers" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    log_path = log_dir / f"{mode}-{timestamp}.log"
    environment = os.environ.copy()
    environment["HF_HUB_DISABLE_TELEMETRY"] = "1"
    environment["PYTHONUNBUFFERED"] = "1"
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"device: {device}\nGPU: {gpu_name}\n")
        log.write(f"Hard time limit: {max_seconds} seconds\n")
        log.write(f"Command: {' '.join(command)}\n")
        log.flush()
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            return_code = process.wait(timeout=max_seconds)
        except subprocess.TimeoutExpired:
            log.write(f"\nTIME LIMIT: stopping process after {max_seconds} seconds.\n")
            log.flush()
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            return_code = 124
    print(
        f"job={mode} exit_code={return_code} log={log_path}",
        flush=True,
    )
    return return_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=("qa", "ner", "summarization", "question_generation"),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "local_4gb.yaml",
    )
    args = parser.parse_args()
    raise SystemExit(run(args.mode, args.config))
