# Sequence model comparison

## Updated run: longer sequences and larger batches

Task: IMDB binary sentiment classification. All models use the same deterministic
20,000-train / 2,000-validation / 2,000-test subset and the same vocabulary.
Measurements below are from one local RTX 3050 run; they are not general benchmarks.

| Model | Accuracy | Precision (macro) | Recall (macro) | Macro-F1 | Confusion matrix (actual × predicted) | Train time (s) | Parameters | Peak VRAM (GiB) | Peak GPU utilization (%) | Batch size | Embeddings |
|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---|
| rnn | 0.7480 | 0.7478 | 0.7474 | 0.7475 | `[[791, 244], [260, 705]]` | 118.3 | 2,010,754 | 0.071 | 43 | 64 | scratch |
| lstm | 0.8170 | 0.8171 | 0.8175 | 0.8170 | `[[831, 204], [162, 803]]` | 85.7 | 2,042,626 | 0.080 | 37 | 64 | scratch |
| gru | 0.8655 | 0.8653 | 0.8654 | 0.8654 | `[[898, 137], [132, 833]]` | 124.0 | 2,032,002 | 0.079 | 36 | 64 | scratch |
| bilstm | 0.8350 | 0.8353 | 0.8342 | 0.8346 | `[[886, 149], [181, 784]]` | 159.6 | 2,085,250 | 0.120 | 39 | 64 | scratch |

Configuration: batch_size=64, grad_accumulation_steps=1, max_seq_len=400, hidden_size=64, epochs_up_to=10, early_stopping_patience=2, lr_scheduler=True, mixed_precision=True, embedding_source=glove.

Device: cuda (NVIDIA GeForce RTX 3050 Laptop GPU). GPU utilization is sampled from nvidia-smi per epoch; peak VRAM is PyTorch's maximum allocated memory.

Updated-run loss curves:
- [rnn](./figures/rnn_loss_seq400.png)
- [lstm](./figures/lstm_loss_seq400.png)
- [gru](./figures/gru_loss_seq400.png)
- [bilstm](./figures/bilstm_loss_seq400.png)

## Previous baseline (preserved)

Original run: 10,000 train / 2,000 validation / 2,000 test, batch size 16, sequence length 128, three epochs. GPU utilization was not recorded.

| Model | Accuracy | Precision (macro) | Recall (macro) | Macro-F1 | Confusion matrix (actual × predicted) | Train time (s) | Parameters | Peak VRAM (GiB) |
|---|---:|---:|---:|---:|---|---:|---:|---:|
| rnn | 0.6215 | 0.6240 | 0.6232 | 0.6212 | `[[595, 440], [317, 648]]` | 32.6 | 1,288,450 | 0.053 |
| lstm | 0.6875 | 0.7120 | 0.6810 | 0.6732 | `[[897, 138], [487, 478]]` | 33.9 | 1,313,410 | 0.054 |
| gru | 0.7185 | 0.7383 | 0.7232 | 0.7151 | `[[609, 426], [137, 828]]` | 33.3 | 1,305,090 | 0.053 |
| bilstm | 0.7360 | 0.7362 | 0.7348 | 0.7350 | `[[796, 239], [289, 676]]` | 51.3 | 1,346,818 | 0.063 |

## Analysis

On this test subset, gru had the highest accuracy (86.6%) and macro-F1 (0.865).

A vanilla RNN repeatedly multiplies gradients through the recurrent transition;
when those products are small, gradients vanish and early context is hard to learn.
Large products can instead explode, so gradient clipping is used. LSTM gates and
a cell state provide controlled paths for information and gradients; GRU combines
update/reset gates in a simpler state. These mechanisms often help on long context,
but they do not guarantee higher scores on this particular subset or seed.

A BiLSTM reads each review in both directions and can use later as well as earlier
words when classifying the whole review. That is useful for offline classification
but is not causal and cannot directly serve next-token generation.

Difficulty labels are generated from readability, term rarity, sentence length,
and technical-term density. They are weak heuristics, not expert ground truth;
scores on them measure agreement with those rules and must not be read as validated
educational difficulty.

The updated numeric table and per-epoch loss traces are also available in
[sequence_models.json](./sequence_models.json) and
[sequence_models.csv](./sequence_models.csv).
