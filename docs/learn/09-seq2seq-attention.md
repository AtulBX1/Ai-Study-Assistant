# Step 9: Sequence-to-sequence models with attention

## What was built and why

This step adds a word-level LSTM encoder-decoder for summarizing articles. It has a
shared vocabulary with `<pad>`, `<unk>`, `<sos>`, and `<eos>`, and three comparable
choices: a no-attention baseline, Bahdanau additive attention, and Luong dot/general
attention. The model is trained from scratch on a bounded CNN/DailyMail subset. This
keeps the implementation aligned with Unit IV rather than using a pretrained model.

The encoder reads the source tokens and the decoder emits one summary token at a time.
The baseline initializes the decoder from the last encoder state. It must compress the
whole source into a fixed-size context vector, which is a bottleneck for long articles.

## Attention and alignment

Soft attention lets each output step choose a weighted mixture of encoder states.
Weights are normalized to add up to one over valid (non-padding) source positions.
This creates a source-to-output alignment matrix without selecting only one token.

* **Bahdanau/additive:** transform the decoder state and each encoder state, add the
  transformed vectors, pass the sum through `tanh`, then take a learned scalar score.
  In shorthand: `score = v · tanh(Wq · query + Wk · key)`.
* **Luong/dot:** compare the decoder query and encoder key with a dot product. If their
  dimensions differ, the query is projected first.
* **Luong/general:** first learn a linear transform of the decoder query, then dot it
  with the encoder key: `score = key · (Wq · query)`.

The scores are softmaxed across source positions; the resulting weights average the
encoder states into a context vector for that output step. A padding mask sets padded
positions to zero probability. Plotting these weights exposes alignment and provides
a useful sanity check, but attention alone does not prove that a generated statement
is factually supported.

## Training and decoding

Teacher forcing feeds the true previous summary token to the decoder during training.
Scheduled sampling sometimes feeds the model's own previous prediction instead.
At inference, only model predictions are available. This difference is **exposure
bias**: an early mistake can change the inputs to later steps and cause a sequence to
drift from the reference.

Greedy decoding selects the highest-probability next token at every step. It is fast,
but a locally best choice need not make the best complete sequence. Beam search keeps
several partial sequences, accumulates log probabilities, and can use length
normalization. Optional n-gram blocking prevents an already emitted trigram from
being repeated. The optional coverage mechanism is deliberately not implemented;
coverage penalties would need additional tuning and validation beyond ordinary
attention.

The trainer supports teacher-forcing ratios and scheduled sampling, gradient clipping,
fp16 autocasting on CUDA, gradient accumulation, checkpoint resume, validation-loss
early stopping, and a per-variant time cap. Peak allocated VRAM is reported per epoch;
CUDA out-of-memory errors include a batch/sequence-length reduction suggestion.

## Evaluation metrics

ROUGE-1/2/L compare overlapping words, word pairs, and longest common subsequences
with reference summaries. They indicate content overlap and recall-oriented coverage,
but a high score does not guarantee factuality. BLEU compares n-gram precision with
brevity adjustment and is more sensitive to exact wording; it is widely used for
machine translation and can under-score valid paraphrases in summarization. Reporting
both offers complementary, imperfect views of generation quality.

## Limitations of classical seq2seq

A fixed word vocabulary maps unseen words to `<unk>`. Recurrent processing can lose
long-range information, and a truncated input cannot preserve details outside its
window. Exposure bias, repetition, and unsupported claims can remain even with
attention and beam search. Unlike a pretrained Transformer summarizer, this compact
from-scratch model must learn language and summarization patterns from the small
training subset. The actual measured results and sampled outputs are recorded in
[`../results/seq2seq.md`](../results/seq2seq.md) and
[`../results/seq2seq_limitations.md`](../results/seq2seq_limitations.md) after training.

## Viva questions and answers

1. **What does an encoder-decoder do?** The encoder converts a source sequence into
   recurrent states; the decoder uses them to produce a target sequence one token at
   a time.
2. **What is the context-vector bottleneck?** A no-attention model must squeeze a long
   source into one fixed-size vector, so information from distant positions can be
   lost.
3. **How do Bahdanau and Luong attention differ?** Bahdanau learns an additive
   compatibility score; Luong compares query and key vectors by dot product, directly
   or after a learned general projection.
4. **What is exposure bias?** Training often conditions on correct earlier target
   tokens, while inference conditions on its own predictions, so mistakes can
   compound.
5. **Why report both BLEU and ROUGE?** BLEU emphasizes generated n-gram precision;
   ROUGE emphasizes overlap/coverage with reference text. Neither alone measures
   factual correctness or semantic equivalence.
