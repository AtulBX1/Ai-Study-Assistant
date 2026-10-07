# Step 7: Modern dense retrieval

## What we built

The assistant now embeds document chunks with `sentence-transformers/all-MiniLM-L6-v2`. During the indexing stage, each chunk receives a normalized vector and a Qdrant point containing its user, document, chunk, page, and section metadata. Chunk rows keep the corresponding vector ID so the point can be replaced or removed later.

Local development uses Qdrant's file-backed mode under `data/qdrant`. Production selects the Qdrant URL adapter with `BACKEND=prod` and `QDRANT_URL`. Both implementations use the same vector-store interface, and retrieval filters by both owner and requested document IDs.

The search registry supports `dense` and `hybrid`. Hybrid retrieval combines dense cosine similarity with BM25 ranks using weighted Reciprocal Rank Fusion (RRF). Its response includes the BM25 and dense component ranks and scores. An optional rerank pass applies `cross-encoder/ms-marco-MiniLM-L-6-v2` to the top 30 candidates and returns the requested top results with both original and cross-encoder scores. If the cross-encoder cannot load or score, the endpoint logs the failure and preserves the original ranking.

The embedding and reranker models load lazily. Configure model names, device, batch size, and `HF_HOME` with environment variables; this step uses CPU and caches model files under `models/hf`. Query rewriting and query expansion have replaceable interfaces with no-op implementations until an LLM-backed strategy is added.

## Why this matters

Keyword retrievers such as BM25 need query terms to overlap with the document. A dense encoder maps a query and a chunk into the same semantic vector space, so related wording can still be close even when they share few words. Dense retrieval can therefore find a relevant chunk for a paraphrase that BM25 misses. It can also lose: a distinctive exact term, acronym, or number may strongly favor BM25.

The bi-encoder embeds chunks and queries independently. This makes vector search efficient at scale, including approximate nearest-neighbor (ANN) search. Qdrant compares the vectors with cosine similarity. The cross-encoder is slower because it reads each query together with each candidate chunk and produces a more targeted relevance score. Reranking improves only the candidate ordering; it cannot recover a relevant chunk that was not among the initial candidates.

Hybrid RRF combines rankings rather than directly comparing BM25 scores with cosine values, whose scales differ. A configurable dense weight balances semantic and lexical ranks, while `RRF_K` controls how quickly lower-ranked results contribute less.

## Key syllabus concept

Dense retrieval is an application of distributed word and sentence representations. A bi-encoder creates reusable embeddings for large collections, while a cross-encoder spends more computation on a small candidate set. Combining both with a lexical retriever demonstrates how semantic similarity and exact matching can complement one another.

## Viva questions

1. **Why can dense retrieval find a paraphrase that BM25 misses?**  
   The encoder learns to map semantically related text near each other even when the exact words differ.

2. **Why normalize vectors before cosine search?**  
   Normalization makes vector length one, so cosine similarity reflects direction rather than magnitude.

3. **What is the difference between a bi-encoder and a cross-encoder?**  
   A bi-encoder embeds query and chunk separately for efficient retrieval. A cross-encoder scores the combined pair more accurately but costs more computation.

4. **How does RRF combine BM25 and dense results?**  
   It gives each result a contribution based on its rank in each list, then adds the weighted reciprocal-rank contributions.

5. **Why rerank only a limited set of candidates?**  
   Cross-encoding every chunk is expensive. The bi-encoder and BM25 first narrow the search, and the cross-encoder refines that smaller set.
