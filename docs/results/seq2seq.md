# Step 9: Classical seq2seq evaluation

Device: NVIDIA GeForce RTX 3050 Laptop GPU. Dataset: `abisee/cnn_dailymail` config `3.0.0`.
Subsets: train=20000, validation=1000, test=1000.

Scores are corpus BLEU and mean example-level ROUGE F1 on the same held-out subset.

| Model | Decode | ROUGE-1 | ROUGE-2 | ROUGE-L | BLEU | Avg. length | Repeated trigrams | Best val loss | Peak VRAM (GiB) | Tokens/s |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| none | greedy | 0.1180 | 0.0078 | 0.0963 | 0.19 | 40.3 | 0.000 | 5.4814 | 0.46 | 4028.2 |
| none | beam | 0.0963 | 0.0077 | 0.0773 | 0.28 | 33.6 | 0.000 | 5.4814 | 0.46 | 4028.2 |
| bahdanau | greedy | 0.1473 | 0.0177 | 0.1166 | 0.44 | 40.7 | 0.000 | 5.3467 | 1.20 | 2400.9 |
| bahdanau | beam | 0.1201 | 0.0153 | 0.0950 | 0.44 | 23.6 | 0.000 | 5.3467 | 1.20 | 2400.9 |
| luong | greedy | 0.1365 | 0.0127 | 0.1093 | 0.24 | 38.4 | 0.000 | 5.3518 | 0.68 | 2764.0 |
| luong | beam | 0.0894 | 0.0098 | 0.0745 | 0.25 | 20.4 | 0.000 | 5.3518 | 0.68 | 2764.0 |

Beam ROUGE-L attention gap (mean Bahdanau/Luong minus no-attention): +0.0075 (attention mean 0.0848, no-attention 0.0773).

The baseline has no learned alignment matrix; its panel below explicitly marks that absence.

## none example

Beam summary: u . s . military says . new : < num > - year - old girl , < num . . . says it is not to the . .

Reference: Membership gives the ICC jurisdiction over alleged crimes committed in Palestinian territories since last June .
Israel and the United States opposed the move, which could open the door to war crimes investigations against Israelis .

Loss curve: [none_loss.png](./none_loss.png)

Attention plot: [attention_none.png](./attention_none.png)

## bahdanau example

Beam summary: new : u . s . secretary of state department says . <unk> : " it is a " of the , " says says . new : " we want to do not want to be " <unk> , " official says .

Reference: Membership gives the ICC jurisdiction over alleged crimes committed in Palestinian territories since last June .
Israel and the United States opposed the move, which could open the door to war crimes investigations against Israelis .

Loss curve: [bahdanau_loss.png](./bahdanau_loss.png)

Attention plot: [attention_bahdanau.png](./attention_bahdanau.png)

## luong example

Beam summary: u . n . secretary - general says .

Reference: Membership gives the ICC jurisdiction over alleged crimes committed in Palestinian territories since last June .
Israel and the United States opposed the move, which could open the door to war crimes investigations against Israelis .

Loss curve: [luong_loss.png](./luong_loss.png)

Attention plot: [attention_luong.png](./attention_luong.png)

## Analysis

This is a small, capped classical-model run, not a pretrained summarizer. The metrics and examples above come from the held-out subset; low or negative attention gaps are reported without implying a guaranteed attention benefit. Truncation, vocabulary OOVs, exposure bias, and limited recurrent context constrain these results.

All scored greedy and beam outputs use trigram blocking, so their zero repeated-trigram rates reflect this decoding guard rather than an absence of repetition in the models. The limitations document includes an actual diagnostic greedy output with blocking disabled, which exhibits repeated trigrams.
