# 12. Quiz engine

The quiz service builds grounded questions from a user's selected ready documents, pages, sections, or chunks. `QuizQuestion` is the validated JSON contract: question text, type, options, correct answer, explanation, chunk ID, page, difficulty, and engine. Question and request sizes are bounded by Pydantic.

## Generation and routing

The classic engine uses Step 10's local T5 highlight format, local NER entities, key terms, and capitalized noun-phrase candidates. It creates multiple-choice and short-answer questions from T5, true/false questions from source statements, and fill-in-the-blank prompts by masking an answer span. Distractors prefer same-type entities and terms from the document, then embedding neighbours. Substrings, aliases, wrong types, duplicates, and very similar terms are filtered. A provider can supply distractors only as a fallback.

The LLM engine calls the configured Step 11 provider with a JSON-only contract. Missing provider configuration, provider errors, rate limits, and private documents route to classic generation. A private document is never included in an external provider prompt. The effective engine and fallback reason are included in the generation report.

## Validation and difficulty

Every question is checked for a usable stem, a source-grounded answer, unique options, and exactly one correct multiple-choice option. The fine-tuned DistilBERT QA model answers each generated question from the same source chunk; token F1 below the configured threshold rejects the question. Similarity rejects repeats. Counts are kept by rejection reason in the quiz report.

Difficulty starts with the Step 8 chunk label and adjusts for answer length, rarity, and reasoning sentences. A requested level is enforced; the quiz response reports the resulting level mix.

## Attempts and grading

Objective questions are graded by exact normalized answer equality. Short answers use semantic similarity and may use a structured LLM rubric when the source is public and a provider is available. Topic totals update `topic_stats`; results include explanations and links to the source page. Retakes copy only missed questions into a new quiz. Exam exports group questions into sections, assign marks, and include the answer marking scheme in PDF or DOCX.

## Viva questions

1. **Why validate generated questions with a QA model?** It catches questions whose answer contradicts or is absent from the cited chunk.
2. **How does the classic engine find answers?** It combines local NER entities, extracted document terms, noun phrases, and T5 highlight-conditioned question generation.
3. **How are distractors filtered?** Candidates must have the right type and must not be aliases, substrings, duplicates, or too similar to the key.
4. **When is an LLM used?** Only when selected and available, and only for non-private source documents; routing falls back to the local classic engine otherwise.
5. **How are short answers graded?** Semantic similarity is the baseline, with a structured rubric score when an allowed provider is available.
# Step 12 quality improvements

The quality runner batches up to four questions in one JSON response per chunk and accepts `--max-requests` (default 12). `QUIZ_LLM_MIN_DELAY_SECONDS` throttles requests; a 429 honors `Retry-After`, then retries with exponential backoff capped by `QUIZ_LLM_BACKOFF_CAP_SECONDS`. It stops after repeated rate limiting and reports requests used, returned questions, and rate-limit status. LLM pass rate is reported as not measurable when fewer than 20 questions return. Parsed responses are cached in-process by chunk id, question type, and prompt version.

Classic generation removes common slide and table noise, selects one complete source sentence of at least eight words, and derives each stem from that sentence. Stem checks reject option debris, artifacts, fragments, and low readability scores. Single-word generic answers require a match in document key terms or named entities. Rejection reasons remain separate in the quality report.

After running `scripts/quiz_quality.py --document-id 2`, export a random sample with `python scripts/quiz_rating.py`. Fill each rating as `good`, `ok`, or `bad`, then compute the good percentage using `python scripts/quiz_rating.py --score`.
