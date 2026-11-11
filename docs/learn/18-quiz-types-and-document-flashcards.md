# Step 18: Quiz Types and Document Flashcards

## What we built

Quiz requests now select one or more question types and split the requested
count across those types. Each report shows requested and produced counts and
the main rejection reasons. Quiz generation supports automatic, offline-only,
and AI-only engines. Automatic mode tries AI for non-private documents and uses
the offline generator to fill any shortages. Private documents stay offline.

Flashcards now come from the document itself: glossary terms, cloze versions of
definition sentences, and (when allowed) AI question-and-answer cards with
quoted evidence. Incorrect quiz answers can be included optionally. Cards save
their source type, page, and evidence, and repeated requests do not create
duplicates.

## Why

Question type quotas make a quiz match a learner's needs and make shortages
understandable. Source-based flashcards work even before a quiz exists. Privacy
routing ensures private study material never reaches an AI provider.

## How it works

The backend allocates quiz quotas in round-robin order. It cleans source text,
validates answers and evidence, tracks reject reasons, and records the engine
and provider for each accepted question. Offline multiple choice uses related
terms from the document as distinct distractors. True/false questions are
balanced at the quiz level.

Flashcard generation first fills an empty glossary from stored key terms and
their defining page sentences. It then builds glossary and cloze cards, requests
evidence-grounded AI cards only for eligible documents, and optionally adds
cards from incorrect quiz attempts. Stable keys and database uniqueness keep
generation idempotent. Local embedding, reranker, and QA models may warm in a
background thread; `SKIP_MODEL_WARMUP=true` disables it.

## Syllabus concept

Evidence-grounded question generation combines text processing with answer
validation. Retrieval models can help rank related terms, but each generated
answer must still be supported by a quoted source sentence and page.

## Viva questions

1. **How is a requested quiz count split across types?** In round-robin order,
   so selected types receive balanced quotas.
2. **What does automatic engine mode do?** It tries AI first for a non-private
   document, then fills remaining quotas offline.
3. **Why are private documents offline-only?** Their source text must not be
   sent to an external provider.
4. **How does a cloze card stay grounded?** It blanks a glossary term in an
   exact defining sentence and stores the original sentence as evidence.
5. **How does the backend report shortages?** It returns requested and produced
   counts plus the most common rejection reasons for each question type.
