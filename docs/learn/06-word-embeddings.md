# Step 6: Classical word embeddings

## What was built

The embedding lab can train owner-scoped CBOW or Skip-Gram Word2Vec models
from a document's Step 4-preprocessed chunks. The model is saved beneath
`models/word2vec/<user-id>/<document-id>/`; it is local development data and is
ignored by Git. Pretrained GloVe vectors are loaded only when requested and are
cached beneath `models/glove/`.

Authenticated `/lab/embeddings` endpoints expose nearest neighbours, cosine
similarity, analogies, side-by-side comparisons, and 2D/3D projections. Local
Word2Vec queries require a document ID so the API can enforce ownership.
Unknown terms produce a clear out-of-vocabulary response and, when possible,
a nearest-spelling suggestion. Projection responses include coordinates,
labels, and KMeans cluster IDs. PCA and t-SNE use scikit-learn; UMAP returns a
clear not-installed response unless its optional package is present.

The `word2vec` search mode averages known word vectors for each chunk and query,
then ranks using cosine similarity. Its chunk-vector cache lives with the
retriever cache and is isolated by user and document set. The retrieval
evaluation runner trains a small CBOW model per document and writes
`docs/results/retrieval_word2vec.csv`. Pretrained data are not downloaded
during startup or ordinary Word2Vec training.

## Vector-space models: one-hot and dense vectors

A vocabulary of `V` terms can represent each word as a one-hot vector of length
`V`: exactly one position is 1 and all other positions are 0. One-hot vectors
are sparse and distinguish words, but have no notion of related meaning:
different terms are orthogonal, even if they are synonyms.

An embedding maps each word to a much shorter, dense vector of real numbers.
Words that appear in similar contexts can acquire nearby vectors. Word2Vec
learns vectors from a document's local context windows, while GloVe learns
vectors from corpus-wide word co-occurrence statistics.

## Word2Vec architectures

CBOW (Continuous Bag of Words, `sg=0`) predicts a missing center word from
nearby context words. It combines context, so it trains quickly and is often
effective for frequent words.

Skip-Gram (`sg=1`) predicts surrounding context words from a center word.
It performs more prediction work but can learn useful representations for
less frequent words when the training corpus is large enough. Both architectures
need enough contextual examples; training on a tiny document is only a
demonstration, not a general-purpose semantic model.

Important hyperparameters:

| Parameter | Meaning | Typical effect |
| --- | --- | --- |
| `vector_size` | Number of values in each word vector | More capacity, more computation and data needed |
| `window` | Maximum context distance around a word | A larger window captures broader topical relationships |
| `min_count` | Ignore words occurring fewer times than this | Reduces rare-word noise, but can remove useful terms in small documents |
| `epochs` | Passes over the training examples | More passes can improve fit, but may overfit a tiny corpus |
| `negative` | Number of sampled false context predictions | Efficiently approximates the full softmax objective |
| `seed` | Random initialization seed | Makes training comparisons repeatable |

## Negative sampling

Predicting a context word with a full softmax requires scoring every vocabulary
word. Negative sampling instead updates the observed center/context pair as a
positive example and a small number of sampled, unobserved pairs as negatives.
It makes training substantially cheaper. The `negative` setting controls the
number of negative examples per positive pair.

## GloVe and co-occurrence

GloVe (Global Vectors) starts with a word-word co-occurrence matrix. Each entry
counts how often two words appear near one another across a corpus. Training
fits word and context vectors so their dot products encode the logarithm of
co-occurrence counts, with weighting to balance rare and frequent pairs. Unlike
this project's document-trained Word2Vec models, the selected
`glove-wiki-gigaword-100` vectors are pretrained on a much broader corpus. The
download is lazy and is limited to this 100-dimensional model.

## Cosine similarity, neighbours, and analogies

Cosine similarity is the dot product divided by both vector lengths:

`cosine(u, v) = (u · v) / (||u|| ||v||)`

It measures angle rather than raw magnitude. A value near 1 indicates similar
directions; a value near 0 indicates little directional similarity; a negative
value indicates opposing directions. A nearest-neighbour endpoint ranks terms
by this value.

An analogy uses vector arithmetic. For example, the query
`king - man + woman` searches for a vector near the result of subtracting
`man` from `king` and adding `woman`. This is an empirical geometric pattern,
not a guarantee of factual or unbiased reasoning. OOV inputs cannot be used
for similarities or analogies.

## PCA, t-SNE, and UMAP

Projection reduces high-dimensional word vectors to two or three dimensions
for plotting. It necessarily loses information; visible distance in a plot
should not be treated as the original cosine score.

- **PCA** is a linear projection onto directions that explain the most
  variance. It is fast and tends to preserve broad/global structure.
- **t-SNE** is a nonlinear visualization that emphasizes local neighbourhoods.
  It can distort distances between far-apart groups; perplexity is capped based
  on the available vocabulary so small vocabularies remain usable.
- **UMAP** is another nonlinear neighbourhood-preserving method. It is optional
  here because its package can add heavy compiled dependencies on Windows.

All projections attach deterministic KMeans cluster IDs computed from the
original vectors, not from the displayed 2D/3D coordinates.

## Key syllabus concept

Unit II moves from sparse symbolic representations to dense distributional
representations: a word's vector captures patterns in the contexts where it
occurs. CBOW and Skip-Gram learn from local context prediction, while GloVe
uses global co-occurrence counts.

## Viva questions

1. **Why are dense embeddings more expressive than one-hot vectors?**  
   Dense embeddings use a compact real-valued vector whose dimensions can
   encode contextual regularities. One-hot vectors only assign a separate
   coordinate to each term, so distinct terms have no built-in similarity.

2. **How do CBOW and Skip-Gram differ?**  
   CBOW predicts a center word from its context. Skip-Gram predicts context
   words from the center word.

3. **What does negative sampling do?**  
   It replaces a costly prediction over the whole vocabulary with a positive
   observed pair and a small set of sampled negative pairs.

4. **How does GloVe use word co-occurrence?**  
   It learns vectors from a global word-word co-occurrence matrix, fitting
   vector dot products to encode co-occurrence statistics.

5. **When would you choose PCA rather than t-SNE or UMAP?**  
   PCA is a fast linear baseline that exposes broad variance structure.
   t-SNE and UMAP are useful for local nonlinear neighbourhoods but can distort
   global distances and are mainly visualization tools.
