# Step 10: Transformer evaluation

Evaluation tables are written from the fixed subsets in
`configs/local_4gb.yaml`; counts below must reflect the rows actually scored.
The selected scored weights are the Trainer checkpoint with the lowest
validation loss (`load_best_model_at_end=True`), not the final update.

## Task scores

| Task | Dataset / split | Evaluation sample size | Metrics |
|---|---|---:|---|
| Extractive QA | `rajpurkar/squad`, validation prefix | Pending training | SQuAD F1 / Exact Match |
| NER | `tner/conll2003`, test prefix | Pending training | Entity precision / recall / F1 |
| T5 summarization | `abisee/cnn_dailymail` 3.0.0, test prefix | Greedy 500; beam 200 | ROUGE-1 / ROUGE-2 / ROUGE-L / BLEU |
| T5 question generation | `rajpurkar/squad`, validation prefix | 200 | ROUGE-L / BLEU |

NER reports PER, ORG, LOC, and MISC entity-level results. QA also evaluates an
unfine-tuned DistilBERT baseline on the first 200 validation examples.

## Runtime and artifacts

The training logs include the actual training duration and peak allocated VRAM
for each completed job. Loss plots are stored under
`models/transformers/loss_curves/`; each completed task also writes its metrics
and exact sample counts to `models/transformers/evaluation.json`. MLflow logs
are enabled when `transformers.mlflow` is true in the selected YAML file.

No score should be described as completed until its evaluation record and
checkpoint exist. GPU memory, subset sizes, and the selected best-checkpoint
path are recorded per task.

## Interpretation limits

DistilBERT and T5-small are intentionally much smaller than large production
models. The runs use small, deterministic prefixes rather than full dataset
training. A score on such a subset is an instructional measurement, not a
claim of production quality. T5 summarization is scored on the first 500
greedy and first 200 beam test examples; Step 9's published aggregate uses
1,000 examples per decoding strategy, so the numbers must not be presented as
a strict apples-to-apples comparison unless Step 9 is rescored on those exact
same examples.
