# Step 10: Transformer evaluation

> Evaluation tables use fixed deterministic subsets defined in `configs/local_4gb.yaml`.
> The selected weights are the Trainer checkpoint with the **lowest validation loss** (`load_best_model_at_end=True`), not the final update.

## Task scores

| Task | Dataset / split | Train size | Val size | Eval size | Key metric |
|---|---|---:|---:|---:|---|
| Extractive QA | `rajpurkar/squad`, validation prefix | 20,000 | 2,000 | 2,000 | SQuAD F1 / Exact Match |
| NER | `tner/conll2003`, test split | 14,041 | 3,250 | 3,453 | Entity-level F1 (seqeval) |
| T5 summarization | `abisee/cnn_dailymail` 3.0.0, test prefix | 10,000 | 1,000 | greedy 500 / beam 200 | ROUGE-1 / ROUGE-L |
| T5 question generation | `rajpurkar/squad`, validation prefix | 20,000 | 500 | 200 | ROUGE-1 / ROUGE-L / BLEU |

### Extractive QA — DistilBERT fine-tuned

Training limit: **30 minutes** (1,800 s wall clock, 2 epochs completed before limit).

| Checkpoint | Exact Match | F1 |
|---|---:|---:|
| Unfine-tuned baseline (200 val examples) | 0.50 | 7.48 |
| Fine-tuned best val-loss checkpoint (2,000 val examples) | **63.15** | **72.29** |

EM and F1 are SQuAD v1 official metrics. Baseline was scored on only 200 examples (no fine-tuning, same DistilBERT weights). Fine-tuned checkpoint: `checkpoints/qa/checkpoint-400`. Training: 20,000 examples, batch 8 × grad_accum 8 = effective batch 64, lr 3e-5.

### Named Entity Recognition — DistilBERT fine-tuned

Training limit: **20 minutes** (1,200 s). All 14,041 CoNLL-2003 train examples used. Evaluated on full 3,453-example test set.

| Entity type | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| PER | 0.967 | 0.960 | **0.964** | 1,617 |
| LOC | 0.900 | 0.918 | **0.909** | 1,668 |
| ORG | 0.841 | 0.866 | **0.853** | 1,661 |
| MISC | 0.740 | 0.789 | **0.764** | 702 |
| **Overall** | **0.880** | **0.899** | **0.889** | 5,648 |

Fine-tuned checkpoint: `checkpoints/ner/checkpoint-660`. Training 3 epochs, batch 8 × accum 8, lr 3e-5.

### T5-small Summarization

Training limit: **40 minutes** (2,400 s). T5-small was **already pre-trained on CNN/DailyMail summarization**, so fine-tuning gains are small — the model starts near its ceiling for this dataset and task. Scored on **first 500 test examples** (greedy) and **first 200 test examples** (beam width 3).

| Decoding | Eval examples | ROUGE-1 | ROUGE-2 | ROUGE-L | BLEU |
|---|---:|---:|---:|---:|---:|
| Greedy | 500 | **0.306** | 0.113 | **0.222** | 0.087 |
| Beam (width 3) | 200 | **0.326** | 0.123 | **0.237** | 0.094 |

Fine-tuned checkpoint: `checkpoints/t5-summarization/checkpoint-750`. Best val loss: 2.165. Training: 10,000 examples, batch 2 × accum 8 = effective batch 16, lr 3e-4.

**Note**: T5-small begins with broad pretrained text-to-text knowledge including summarization. The relatively high ROUGE scores compared to the Step 9 seq2seq models primarily reflect pretraining, not fine-tuning alone.

### T5-small Question Generation

Training limit: **30 minutes** (1,800 s). **1 epoch completed** (~25 minutes). Evaluated on first 200 validation examples.

| ROUGE-1 | ROUGE-2 | ROUGE-L | BLEU |
|---:|---:|---:|---:|
| **0.442** | 0.231 | **0.409** | 0.142 |

Fine-tuned checkpoint: `checkpoints/t5-question-generation/checkpoint-1000`. Best val loss: 1.832. Training: 20,000 examples, batch 2 × accum 8, lr 3e-4. Trained from SQuAD context→question pairs using `generate question: {context} <hl> {answer} <hl>` prompt format.

## Runtime and artifacts

| Task | Training time | Peak VRAM | Device |
|---|---:|---:|---|
| QA | 1,652 s (~27 min) | 1.27 GiB | CUDA (RTX 3050 Laptop) |
| NER | 273 s (~5 min) | 1.27 GiB | CUDA |
| T5 summarization | 1,195 s (~20 min) | 1.15 GiB | CUDA |
| T5 question generation | 1,501 s (~25 min) | 1.15 GiB | CUDA |

Loss curves are stored under `models/transformers/loss_curves/` (regenerated with training loss ÷ gradient accumulation steps). Full metrics are in `models/transformers/evaluation.json`.

## Interpretation limits

DistilBERT and T5-small are intentionally much smaller than large production models. The runs use small, deterministic prefixes rather than full dataset training. A score on such a subset is an instructional measurement, not a claim of production quality.

T5-small pre-training on CNN/DailyMail means fine-tuning primarily adjusts the learning-rate schedule rather than building summarization capability from scratch. This is why the ROUGE-L improvement over the Step 9 seq2seq models is large — it reflects architectural and pretraining advantages, not just fine-tuning.
