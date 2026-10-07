# Step 8: Recurrent sequence models

## What we built

The sequence-model package shares the Step 4 text normalization and tokenizer,
then builds a frequency-limited vocabulary with `<pad>` and `<unk>` IDs. Padded
review and document-chunk batches carry their original lengths into a packed
sequence so the recurrent network does not treat padding as text.

The classifier is an embedding layer followed by a from-scratch vanilla RNN,
LSTM, GRU, or bidirectional LSTM. It can initialize its embedding matrix from
local Step 6 Word2Vec or GloVe vectors when files are already present; no
pretrained-vector download is started automatically. The shared trainer uses
fp16 on CUDA, gradient accumulation and clipping, validation-loss scheduling
and early stopping, deterministic seeds, and resumable checkpoints. It logs
peak allocated GPU memory each epoch and gives batch/sequence-length guidance
on out-of-memory errors.

The local 4 GiB configuration is deliberately small; a separate DGX config
uses larger batches and hidden dimensions. The IMDB comparison uses one fixed
train/validation/test subset for all four model types. Document-chunk
difficulty labels are transparent heuristics from readability, corpus-relative
term rarity, sentence length, and technical-term density. They are saved as
**weak labels**, not human-verified educational judgments.

A compact character-level LSTM trains on extracted PDF text. Its demonstration
contrasts teacher forcing (using the true previous character at each step) with
free-running decoding (feeding each prediction back as the next input). The
same recurrent model can be trained with truncated backpropagation through
time (BPTT), which carries state between short chunks but detaches gradients at
chunk boundaries.

## Why this matters

In a sequence, order and prior context affect the meaning of each item. A
recurrent network updates a hidden state as it reads each token, so it can use
context without converting a text into an unordered bag of words. The API loads
saved model weights only when a classifier request arrives. Difficulty
predictions can also be stored on owner-scoped document chunks.

## Key syllabus concept

For token embedding \(x_t\), a vanilla RNN computes
\[
h_t = \tanh(W_{xh}x_t + W_{hh}h_{t-1} + b_h), \qquad
y_t = W_{hy}h_t + b_y.
\]
During backpropagation through time, gradients are multiplied by recurrent
Jacobians across steps. Repeated factors with norm below one cause vanishing
gradients; factors above one can cause exploding gradients. Gradient clipping
limits the norm of an update, but does not by itself solve vanishing gradients.

An LSTM adds a cell state \(c_t\) and gates. With
\(z_t=[h_{t-1},x_t]\), it computes
\[
f_t=\sigma(W_fz_t+b_f),\quad i_t=\sigma(W_iz_t+b_i),\quad
\tilde c_t=\tanh(W_cz_t+b_c),\quad
c_t=f_t\odot c_{t-1}+i_t\odot\tilde c_t,\quad
o_t=\sigma(W_oz_t+b_o),\quad h_t=o_t\odot\tanh(c_t).
\]
The forget, input, and output gates regulate retaining, writing, and exposing
information. A GRU uses update and reset gates and merges the cell and hidden
state, often with fewer parameters. Both gated models can preserve useful
signals over longer spans than a basic RNN, although the result depends on the
data and training setup.

A bidirectional RNN processes the sequence left-to-right and right-to-left and
joins both final states. It can use future as well as past context and is useful
for whole-document classification, but is not appropriate when predictions
must be causal.

Teacher forcing supplies the true previous token while training a next-token
model. Free-running (autoregressive) generation feeds the model's own last
prediction back. The latter can drift because a mistaken token changes later
context; the difference is sometimes called exposure bias. Truncated BPTT
breaks a long training sequence into shorter windows. It preserves a carried
hidden state but detaches it at each boundary, reducing memory at the cost of
gradient information across that boundary.

Packed sequences pair padded token IDs with lengths. They skip trailing
padding in the recurrent computation; lengths remain on the CPU for PyTorch's
packing utility. This reduces wasted work and prevents padded positions from
changing the classifier state.

For a class, precision is \(TP/(TP+FP)\), recall is \(TP/(TP+FN)\), and
\(F1=2PR/(P+R)\). Macro-F1 computes F1 per class and averages classes equally.
The confusion matrix here uses actual labels as rows and predicted labels as
columns, making false positives and false negatives visible. Accuracy is the
fraction of all predictions that are correct; it can hide poor minority-class
performance.

## Viva questions

1. **Why can a vanilla RNN forget early words?**  
   Backpropagation repeatedly multiplies recurrent Jacobians. If their
   magnitudes are small, the gradient reaching early steps vanishes.

2. **What does the LSTM forget gate do?**  
   It scales the previous cell state, determining how much past information
   continues to the next step.

3. **How does a GRU differ from an LSTM?**  
   A GRU combines memory and hidden state and uses update/reset gates; it often
   has fewer gates and parameters.

4. **When is a bidirectional model inappropriate?**  
   In causal tasks such as streaming or next-token generation, because it uses
   tokens from the future.

5. **How do precision, recall, and macro-F1 differ?**  
   Precision measures correctness among predicted positives, recall measures
   coverage of actual positives, and macro-F1 averages each class's harmonic
   mean of precision and recall equally.
