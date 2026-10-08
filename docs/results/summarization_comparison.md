# Step 9 seq2seq and Step 10 T5-small comparison

Step 9's existing evaluation reports metrics on 1,000 leading
CNN/DailyMail-v3.0.0 test examples for each decoding strategy. T5-small uses
the same dataset and the leading test examples, scoring 500 greedy and 200
beam outputs as configured. These are subsets of the same test prefix, but
the sample counts differ. Step 9 model checkpoints are not present in the
local `models/seq2seq/` directory, so its models cannot currently be rescored
on matching 500/200 subsets. The published figures are therefore context, not
a strict paired comparison.

| Model | Decode | Test examples | ROUGE-1 | ROUGE-2 | ROUGE-L | BLEU |
|---|---|---:|---:|---:|---:|---:|
| none | greedy | 1,000 | 0.1180 | 0.0078 | 0.0963 | 0.19 |
| Bahdanau | greedy | 1,000 | 0.1473 | 0.0177 | 0.1166 | 0.44 |
| Luong | greedy | 1,000 | 0.1365 | 0.0127 | 0.1093 | 0.24 |
| none | beam | 1,000 | 0.0963 | 0.0077 | 0.0773 | 0.28 |
| Bahdanau | beam | 1,000 | 0.1201 | 0.0153 | 0.0950 | 0.44 |
| Luong | beam | 1,000 | 0.0894 | 0.0098 | 0.0745 | 0.25 |
| T5-small | greedy | 500 | Pending training | — | — | — |
| T5-small | beam (width 3) | 200 | Pending training | — | — | — |

## Honest interpretation

The recurrent Step 9 systems were trained from scratch with a limited
vocabulary, while T5-small begins with broad pretrained text-to-text
knowledge. The task, data prefix, and decode subsets must still match before
attributing a metric difference to architecture or pretraining. Beam search
does not guarantee better ROUGE; Step 9 itself shows lower ROUGE for some beam
outputs. T5 results and representative outputs are added by the bounded
training/evaluation run, if that job completes within its 40-minute limit.

All T5 test scores use the checkpoint selected by lowest validation loss.
