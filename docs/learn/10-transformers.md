# Step 10: Transformers and pretrained language models

## What we built and why

This step adds small, pretrained Transformer models to the study assistant. A
Transformer can use information from the whole input in parallel, rather than
reading one word at a time like an RNN. Fine-tuning lets a model reuse language
patterns learned from a large general corpus for a focused task such as finding
an answer span, recognizing names, summarizing an article, or writing a question.

The training scripts use DistilBERT for extractive question answering and
named-entity recognition, and T5-small for text-to-text summarization and
question generation. They use fixed dataset prefixes, save the checkpoint with
the lowest validation loss, and report the actual evaluation sample counts.
The API loads a model only when requested and checks document ownership before
accessing private text. If evidence or trained weights are missing, it reports
that clearly instead of inventing an answer.

## How the key ideas work

### Self-attention: query, key, and value

Each input token is turned into three learned vectors:

* A **query** asks what information this token needs.
* A **key** describes information a token can offer.
* A **value** carries that information.

The model compares queries with keys, scales the scores, and uses a softmax to
make weights. It combines the values using those weights. Thus, the
representation of a word such as “it” can use the earlier noun that it refers
to. The `/lab/attention` API returns these weights for each DistilBERT layer and
head so a frontend can visualize them.

### Multi-head attention and position

Instead of learning one attention pattern, **multi-head attention** learns
several in parallel. Different heads can focus on different relationships,
then their outputs are combined.

Self-attention alone does not know word order. The original Transformer adds
**sinusoidal positional encodings** to token embeddings. Even dimensions use a
sine and odd dimensions use a cosine at different frequencies. The
`/lab/positional-encoding` API returns this matrix for plotting.

### Encoder and decoder blocks

An **encoder** reads the input and creates contextual representations. BERT and
DistilBERT are encoder models. A **decoder** generates a sequence one token at a
time using causal self-attention, which prevents it from looking at future
tokens. Encoder-decoder models such as T5 first encode the source and then
generate an output while attending to it.

### Tokenizers: BPE, WordPiece, and SentencePiece

A tokenizer maps text into vocabulary IDs. It may split a rare word into
smaller pieces instead of requiring every whole word to be in its vocabulary.

* **BPE** repeatedly joins frequent neighboring symbols. GPT-2 uses byte-level
  BPE, so even unusual characters can be represented as byte pieces rather
  than an out-of-vocabulary word.
* **WordPiece** chooses frequent subword pieces; DistilBERT marks continuation
  pieces with `##`. A character that is not in its vocabulary can become
  `[UNK]`.
* **SentencePiece** learns subword units directly from raw text and can use
  either BPE or unigram segmentation. T5 uses SentencePiece and commonly shows
  a visible word-boundary marker in token displays.

Numbers, emoji, and rare words can therefore have different token counts and
piece boundaries. The `/lab/tokenizers` API compares the three tokenizers on
the same input and returns both tokens and IDs.

### BERT, GPT, and T5 objectives

**BERT** learns from masked language modeling: some input tokens are hidden and
the model predicts them using surrounding context. Original BERT also used next
sentence prediction. DistilBERT is a smaller model distilled from BERT; it
retains useful encoder representations while using fewer parameters.

**GPT** uses causal language modeling. It predicts the next token from previous
tokens only. This left-to-right objective supports text generation.

**T5** treats every task as text-to-text. A prefix such as `summarize:` tells it
which task to perform; the target is another text sequence. Question generation
uses a `generate question:` prompt and marks the answer with `<hl>` tokens.

### Transfer learning and fine-tuning

Pretraining teaches broad language patterns from a large corpus. **Transfer
learning** starts a task model from those pretrained weights. **Fine-tuning**
then updates some or all weights using a smaller labeled dataset. The local
scripts use small batch sizes, gradient accumulation, fp16, gradient
checkpointing, and explicit time limits to respect a 4 GB GPU.

### Extractive QA and NER

For **extractive question answering**, DistilBERT reads a question and a
context. Two prediction heads assign a score to each token as a possible answer
start and end. The best valid pair identifies a span in the original context.
The API preserves character offsets, chunk ID, and page so the answer can be
highlighted and cited. It returns “no answer found” if its confidence is below
the configured threshold.

For **named-entity recognition**, a token classifier predicts labels such as
`B-PER` (beginning of a person name) and `I-PER` (inside a person name). A
subword tokenizer may split one word into several pieces. During training, the
first sub-token receives the word label and later sub-tokens are masked with
`-100`; otherwise a word split into three pieces would be counted as three
different labels. Reported NER scores are entity-level scores computed with
seqeval.

## Five viva questions and answers

1. **What do query, key, and value do in self-attention?**  
   The query represents what a token is looking for, keys represent what
   tokens offer, and values carry the information combined using attention
   weights.

2. **Why does a Transformer need positional information?**  
   Self-attention can compare all tokens without preserving their order, so
   position encodings tell the model where each token occurs.

3. **How does BERT differ from GPT during pretraining?**  
   BERT predicts masked tokens using both sides of context; GPT predicts the
   next token using only the preceding context.

4. **Why are later WordPiece sub-tokens masked during NER training?**  
   The labels describe words, not subword fragments. Labeling only the first
   piece avoids counting one word multiple times.

5. **What does extractive QA return, and how does it differ from T5?**  
   Extractive QA selects a start and end token from supplied evidence. T5
   generates an output sequence, so it can paraphrase but must be checked
   against the source.
