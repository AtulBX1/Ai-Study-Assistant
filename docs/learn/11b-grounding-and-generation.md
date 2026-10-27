# 11b: Grounded Chat and Generation Strategies

Step 11b builds on the existing RAG chat service. Chat messages retain per-answer grounding metadata and an evidence explanation; the authenticated `/lab/generate` and `/lab/perplexity` endpoints are a separate, local-only language-model playground.

## Hallucination guard and grounding

Retrieval first ranks document chunks, then the cross-encoder reranks candidates. Before generation, chat compares the top rerank score to `RAG_RETRIEVAL_CONFIDENCE_THRESHOLD`. If there is no chunk or the score is below the configured threshold, it returns exactly `not found in the document` and does not call a generator. The default threshold is `0.0` because reranker output scales vary by model and must be calibrated before adopting a stricter deployment threshold. When a reranker is unavailable, the existing retrieval score is the documented fallback signal.

After generation, every answer sentence is checked against retrieved chunks. The checker uses cosine similarity from the existing sentence-transformer only when that model is already cached locally; otherwise the offline keyword-overlap rule is used. Similarity alone is not enough: the answer also needs lexical overlap. A sentence is marked unsupported when no chunk passes the configured `RAG_GROUNDING_SENTENCE_THRESHOLD` plus overlap rule. `grounding_score` is the fraction of answer sentences marked supported, from 0 through 1; `unsupported_sentences` lists the remainder. This is a lightweight heuristic, not an entailment model or a guarantee that supported text is true.

The stored explanation contains the retrieved chunk text, retrieval and rerank scores, hybrid score components when available, answer sentences matched to each chunk, character highlight offsets local to each chunk, provider label, response mode and latency. Citation objects carry the same chunk-local highlight offsets. Explanation content is returned with the owning session only.

## Generation playground (local-only)

The endpoints require authentication. `/lab/generate` takes a prompt and 1–6 settings; each setting chooses `greedy`, `beam`, `top_k`, or `top_p`, with bounded token count, beam width, `top_k`, `top_p`, temperature and repetition penalty. Results include generated text and selected-token probabilities. These small models are next-token language models, not instruction-tuned chat assistants. Generation is intentionally deterministic for greedy/beam; top-k/top-p sample from the filtered distribution.

`/lab/perplexity` calculates the exponentiated mean next-token cross-entropy for a text sample. Lower perplexity indicates the model assigned higher probability to that sequence; it is not an answer-quality score and is only comparable with the same tokenizer/model and evaluation setup. The default is DistilGPT-2 (GPT-2 can be selected by `RAG_PLAYGROUND_MODEL`). Models are lazy-loaded, local-cache-only; missing torch, Transformers, tokenizer, or weights produce a clear 503 without a download attempt. The generation lab does not call a hosted model or alter the chat provider.

## Optional tracing

Langfuse tracing is disabled when either `LANGFUSE_PUBLIC_KEY` or `LANGFUSE_SECRET_KEY` is absent. The integration is optional and imported only when configured. It records question/answer text plus provider, mode and grounding score; operators should enable it only where their data retention policy permits.

## Calibration

Run the offline diagnostic with:

```bash
uv run --directory backend python scripts/calibrate_chat_grounding.py
```

It reads the workspace PDF at `data/real_docs/nlp_notes.pdf`, constructs 30 source-sentence questions and 15 out-of-domain questions, uses the already-cached local reranker, and writes counts, score distribution, per-question diagnostics and caveats to `docs/results/chat_grounding.md`. It does not download model weights. The benchmark is a small, template-generated diagnostic; it is not a human-labeled or statistically representative evaluation. Set the refusal threshold based on a larger reviewed set and the exact deployed reranker.

## Viva questions

### 1. Why do retrieval confidence and grounding score measure different things?
Retrieval confidence estimates whether the question found a relevant source chunk before generation. Grounding score checks whether the sentences that were actually generated have evidence overlap with retrieved text. A strong retrieval result can still lead to an unsupported claim, and relevant retrieval can fail if wording differs.

### 2. Why combine sentence similarity and keyword overlap?
Embeddings can identify semantic similarity but may treat a related topic as evidence even when a claim is not stated. Keyword overlap helps require shared evidence terms. The combination is still a heuristic and can miss valid paraphrases or contradictions.

### 3. How does greedy decoding differ from beam search?
Greedy decoding selects the most likely next token at every step and is fast, but a locally best token can lead to a weaker complete sequence. Beam search retains several high-scoring partial sequences and chooses among their continuations, spending more compute for a broader search.

### 4. What do top-k, top-p, and temperature control?
Top-k restricts choices to the k highest-logit tokens. Top-p keeps the smallest high-probability set whose cumulative mass reaches p. Temperature rescales logits before softmax: lower values sharpen the distribution, while higher values flatten it. These settings affect diversity, not factuality.

### 5. What does perplexity tell us, and what does it not tell us?
Perplexity is the exponentiated average negative log probability of next tokens under a language model. It reflects how expected the sequence is to that model. It does not establish factual correctness, grounding, or usefulness, and comparisons require the same model/tokenizer and protocol.
