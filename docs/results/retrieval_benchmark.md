# Retrieval benchmark

## Corpus and evaluation set

The supplied PDF went through the normal `/documents/upload` and local background-ingestion flow. It produced 114 pages and 199 persisted chunks. The evaluation loader mirrors ingestion text, heading, and table extraction and recreates the same 199 chunks. The editable question set is [`data/eval/questions_real.json`](../../data/eval/questions_real.json): 42 keyword-style, paraphrased, and multi-sentence questions; all are marked `needs_review: true`.

Metrics are macro-averaged at `k=5`. Average latency is per query and excludes PDF parsing, indexing, and model loading.

## Results

| Retriever | Precision@k | Recall@k | MRR | nDCG@k | Average latency/query (ms) |
|---|---:|---:|---:|---:|---:|
| tfidf | 0.1857 | 0.4921 | 0.6667 | 0.5313 | 0.608 |
| bm25 | 0.1952 | 0.5119 | 0.6905 | 0.5514 | 0.650 |
| word2vec | 0.0333 | 0.0675 | 0.1429 | 0.0847 | 2.195 |
| dense | 0.1952 | 0.5238 | 0.7143 | 0.5666 | 23.946 |
| hybrid | 0.1905 | 0.5060 | 0.7143 | 0.5530 | 24.994 |
| hybrid+rerank | 0.1952 | 0.5258 | 0.6905 | 0.5624 | 1302.611 |

## Analysis

BM25 had Precision@5 0.1952, Recall@5 0.5119, and MRR 0.6905; TF-IDF scored 0.1857, 0.4921, and 0.6667. BM25's term-frequency saturation and length normalization can help exact term matches, while TF-IDF weights rarer terms without BM25's length adjustment.

Word2Vec scored Precision@5 0.0333, Recall@5 0.0675, and MRR 0.1429. Its vectors are trained only on this small, narrow corpus and averaged over each chunk, so those learned word neighborhoods are weak evidence for the varied evaluation queries.

Dense retrieval scored Precision@5 0.1952, Recall@5 0.5238, and MRR 0.7143. Hybrid scored 0.1905, 0.5060, and 0.7143; RRF helps only when semantic and lexical rankings contribute complementary evidence. Hybrid plus reranking scored 0.1952 Precision@5, 0.5258 Recall@5, and 0.6905 MRR. It has greater latency because a cross-encoder jointly scores each query-candidate pair.

### Dense versus BM25 examples

Dense found relevant chunk(s) [35] for "Why can an especially aggressive word-reduction method make the resulting text harder to read?"; BM25 did not return a labeled relevant chunk in its top-5.
Conversely, BM25 found relevant chunk(s) [37] for "What drawback is associated with the Lancaster stemmer?" while dense did not. This shows the value of lexical matching when query wording overlaps the notes.

## Indexing memory

Reindexing the 199 chunks through the normal document reindex endpoint on CPU peaked at 675.3 MiB process working set (251.6 MiB at process start; a 423.7 MiB increase). Local Qdrant data is stored under the repository's `data/qdrant` directory.

## GloVe analogy check

The requested `king - man + woman` analogy run could not complete: the upstream GloVe model download connection was reset. No analogy result is claimed; the download was not retried.
