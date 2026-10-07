# Step 5: Chunking and retrieval baseline

## What was built

The indexing stage now turns extracted pages into sentence-aware chunks and
stores them with page ranges, section titles, token counts, and stable
per-document indices. `POST /documents/{id}/rechunk` rebuilds an owned
document's chunks with caller-selected size and overlap. Authenticated
`POST /search` supports TF-IDF and BM25 and returns ranked source chunks.
Step 6 adds document-trained Word2Vec retrieval as a third classical mode.
Retriever indexes are cached separately for each user and document set; a
change to chunk content produces a new cache fingerprint.

The evaluation runner reads editable page- or chunk-labeled questions, reports
Precision@k, Recall@k, MRR, and nDCG, and writes a CSV summary. MLflow logging
is optional (`--mlflow` or `RETRIEVAL_EVAL_MLFLOW=true`); CSV results do not
depend on MLflow.

## Chunking trade-offs

Chunks are assembled from complete sentences and prefer heading, paragraph,
and sentence boundaries. A sentence longer than the configured limit is split
only between whitespace-delimited words. The default chunk size is 400 tokens
with 50 tokens of overlap.

Small chunks are precise: they contain less unrelated material, and their
page citations are narrow. They may omit context that an answer needs and
create more index entries. Larger chunks retain more context and reduce index
size, but can include distracting terms and cite a wider page range.

Overlap repeats a small amount of text from one chunk in the next. It helps
when a fact crosses a boundary, but excessive overlap duplicates retrieval
results and index storage. Overlap is retained in whole sentences, so the
actual repeated token count can be smaller than the configured maximum.

## TF-IDF cosine similarity

TF-IDF weights a term by how often it appears in a chunk and how uncommon it is
across the indexed chunks. Common terms receive less weight; discriminative
terms receive more. This implementation applies the same Step 4 normalization,
tokenization, punctuation handling, and stop-word removal to queries and
chunks.

TF-IDF vectors are L2-normalized. Their dot product is cosine similarity:

| Vector | Terms `(photosynthesis, chlorophyll)` |
| --- | --- |
| Query | `(1, 1)` |
| Chunk A | `(1, 1)` |
| Chunk B | `(1, 0)` |

The query and Chunk A have cosine similarity `1.0`. The query and Chunk B have
similarity `1 / sqrt(2)`, about `0.707`. Similarity is between 0 and 1 for
these non-negative vectors; higher means a closer match.

## BM25

BM25 is a probabilistic term-matching ranker. Term frequency has **saturation**:
seeing a query term several times helps, but each extra repetition contributes
less than the previous one. Its length-normalization term balances long chunks
against short chunks so long text does not win merely because it has more
opportunities to contain query words. The baseline uses the `rank-bm25`
Okapi implementation and shared Step 4 tokens.
For tiny corpora where Okapi IDF becomes negative, its magnitude is used so an
exact lexical match does not rank below a nonmatch; chunks with no query-term
overlap are excluded.

TF-IDF cosine similarity compares normalized weighted vectors and is useful
for broad lexical similarity. BM25 directly scores query-term matches with
saturation and length normalization. Both are lexical baselines: neither
understands synonyms unless their words overlap.

## Ranking metrics with a worked example

Suppose the first three retrieved chunks are `[X, A, B]`, the relevant chunks
are `{A, B}`, and `k = 2`. The top two are `[X, A]`.

| Metric | Calculation | Result |
| --- | --- | ---: |
| Precision@2 | 1 relevant result / 2 returned positions | 0.50 |
| Recall@2 | 1 found relevant chunk / 2 relevant chunks | 0.50 |
| MRR | First relevant result is at rank 2: `1 / 2` | 0.50 |
| nDCG@2 | DCG is `1/log2(3)`; ideal DCG is `1 + 1/log2(3)` | 0.387 |

Precision@k measures how much of the returned top-k is relevant; recall@k
measures how much of the known relevant set was found. Mean reciprocal rank
(MRR) focuses on the first relevant result. Normalized discounted cumulative
gain (nDCG) rewards relevant results near the top and compares their discounted
gain to an ideal ordering. These metrics are macro-averaged over the labeled
questions by the evaluation script.

Page-based labels treat every chunk overlapping a labeled page as relevant.
Labeled questions are drafts; review and correct them before interpreting
evaluation scores.

## Key syllabus concept

TF-IDF connects text preprocessing with sparse vector-space retrieval and
cosine similarity. BM25 is a classical lexical ranking method that improves
term-frequency saturation and document-length normalization. Chunk boundaries
determine both the retrieval unit and the page-level evidence that can be
cited.

## Viva questions

1. **Why split a document into chunks instead of indexing the whole PDF?**  
   Smaller chunks let a search result focus on one topic and give a narrower
   page citation. Their boundaries must still preserve enough context.

2. **Why use overlap between adjacent chunks?**  
   Overlap preserves context when an important sentence or idea falls near a
   boundary. Too much overlap stores duplicate text and can return redundant
   results.

3. **How does cosine similarity compare two TF-IDF vectors?**  
   It computes their dot product after L2 normalization. A score near one
   indicates similar term-weight direction, independent of vector magnitude.

4. **What do BM25 saturation and length normalization do?**  
   Saturation gives diminishing returns for repeated terms. Length
   normalization balances long and short chunks instead of favoring length
   alone.

5. **How do Precision@k and Recall@k differ?**  
   Precision@k is the relevant fraction of the top-k results. Recall@k is the
   fraction of all labeled relevant items that appear in those results.
