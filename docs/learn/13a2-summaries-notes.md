# Step 13a-2: Grounded Summaries, Chapter Notes, and Cheat Sheets

## What we built

A multi-engine summarization and study-synthesis pipeline for learning materials:
1. **Extractive Engine**: Selects highly salient sentences via TF-IDF centrality and positional weighting, filters near-duplicates, and preserves exact source sentence order. Requires no machine learning weights or external network calls.
2. **T5 Engine**: Uses fine-tuned local seq2seq transformer weights (T5-small) with 512-token chunks, tri-gram blocking (`no_repeat_ngram_size=3`), repetition suppression, and strict pre-import weight validation that falls back to extractive summarization if weights are absent.
3. **LLM Engine**: Provider chain integration with token budgeting (< 1,500 input tokens per section), private document isolation, cached completions, and mandatory bullet evidence validation that rejects ungrounded statements. Under rate limits, it returns partial completions with automatic local fallback.
4. **Map-Reduce Architecture**: Long documents are segmented into chapter headings or ~10-page blocks; each section is summarized independently (Map), and the outputs are synthesized into a coherent short summary (Reduce).
5. **Rule-Based Notes & Cheat Sheets**: Generates Markdown chapter notes (section headers, glossary definitions, main extractive points, in-text examples) and single-page cheat sheets (top terms, mathematical formulas/code lines, key facts) with explicit page references and zero external LLM dependencies.

## Why

Students need concise study aids at varying granularities (short summaries, section-by-section breakdowns, quick reference cheat sheets). However:
- Pure abstractive models can hallucinate plausible yet fabricated facts.
- Long PDF documents exceed standard LLM context windows or waste budget.
- Private learning materials must never leak to third-party cloud APIs.
- Production systems must gracefully degrade across rate limits and hardware constraints.

Strict grounding checks, source page citations, and fallback chains guarantee reliable study tools even offline or without GPU resources.

## How it works

### Section Segmentation & Chunk Filtering
Documents are partitioned by structure:
- If structured headings are detected on pages, sections are partitioned by heading titles.
- If headings are absent, contiguous blocks of ~10 pages form default sections.
- Outline and table-of-contents chunks (fewer than 40 words of complete sentences or bullet fragments) are filtered out automatically.

### Engines & Ordered Fallback
When a request asks for an engine, the orchestrator attempts the requested engine, automatically falling back in the chain: `LLM -> T5 -> Extractive`:
- **Extractive**: Tokenizes sentences, computes sentence TF-IDF salience normalized by length, rewards introductory and concluding positions, prunes near-duplicates (Jaccard token overlap > 0.55), and sorts selected sentences by original document order.
- **T5**: Verifies that `models/transformers/t5-summarization/config.json` exists on disk *before* importing PyTorch or Hugging Face libraries. If weights are missing, it falls back to extractive summarization with an explicit reason logged in `fallback_reason`.
- **LLM**: Uses the Step 11 provider chain and dispatches one prompt per section with strict formatting instructions (`- Point: ... | Evidence: ...`). It normalizes whitespace and verifies that every proposed evidence sentence exists in the section text. Any ungrounded bullet is rejected. If a 429 rate limit is encountered, completed sections are preserved and remaining sections fall back immediately to local extractive synthesis without looping. Private documents (`document.is_private = True`) are blocked from external APIs and routed locally.

### Map-Reduce for Short Summaries
- **Map**: Summarizes individual sections/chapters into representative statements.
- **Reduce**: Aggregates intermediate section statements and ranks them with sentence centrality to extract the top 3–5 most informative sentences spanning the whole document range.

### Rule-Based Notes & Cheat Sheets
- **Chapter Notes**: Collects section headers, retrieves saved glossary definitions from Step 13a-1 only when grounded in the cited page, extracts top main points, isolates sentences matching example indicators (`for example`, `e.g.`, `such as`), and affixes page citations `[p. X]`.
- **Cheat Sheet**: Formats a single-page markdown document containing top terms with 1-line definitions, math formulas or code syntax identified via regex patterns, and key factual sentences.

## Syllabus concept

1. **Extractive vs. Abstractive Summarization**: Extractive methods select verbatim sentences from source documents based on statistical salience (word frequency, centrality, position). Abstractive methods rephrase and generate novel sentence structures using sequence-to-sequence models (e.g., T5) or autoregressive LLMs, which increases readability but risks hallucinations.
2. **Map-Reduce Summarization**: A distributed or hierarchical technique for processing long documents exceeding a model's context length. Long texts are split into sections, mapped to intermediate summaries, and reduced into a compact global overview.
3. **Grounding & Evidence Attribution**: Verifying generated text by checking that every claim links to verbatim evidence in the primary source, eliminating unsupported statements.
4. **Data Isolation & Privacy**: Guarding sensitive or private educational materials from third-party APIs by enforcing local computation.

## Viva questions

1. **What is the difference between extractive and abstractive summarization?**
   *Answer*: Extractive summarization identifies and extracts existing sentences from the text without modification. Abstractive summarization generates new phrasing and sentences using language models, paraphrasing key concepts.
2. **How does map-reduce summarization handle long documents?**
   *Answer*: It chunks or partitions the document into sections, generates summaries for each section independently (Map step), and then summarizes the combined section summaries to produce a concise final synthesis (Reduce step).
3. **How does the system ensure LLM summaries are grounded and avoid hallucinations?**
   *Answer*: The LLM is prompted to provide an exact copied evidence sentence for every bullet point. The backend normalizes whitespace and verifies that the evidence sentence is an exact substring of the source page text; ungrounded bullets are rejected.
4. **Why check for T5 weights before importing PyTorch and Transformers?**
   *Answer*: Heavy ML frameworks introduce substantial import overhead, memory allocations, and potential crashes if CUDA/dependencies are misconfigured. Verifying file existence first allows instantaneous, clean fallback to the lightweight extractive engine.
5. **How does the pipeline handle external rate limits (HTTP 429)?**
   *Answer*: Rather than hanging in an infinite retry loop, it preserves the partial summaries already generated by the LLM, logs the rate limit in `fallback_reason`, and completes the remaining sections using the local extractive engine.
