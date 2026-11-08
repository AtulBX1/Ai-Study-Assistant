# Step 17a: Quiz and Flashcard UI

## What we built

The study screens now let a learner make a quiz from a ready PDF, answer one question at a time, review the result, and practice document-backed flashcards. The result screen includes a per-topic accuracy chart and links back to each source page.

## Why it matters

Quizzes help check understanding. Flashcards use active recall: the learner tries to remember a fact before seeing the answer. Repeated reviews use the backend's spaced-repetition schedule so harder cards come back sooner.

## How it works

The frontend uses the typed API client, which adds authentication and refreshes the session when needed. Quiz generation sends the document, optional page or topic scope, question count, difficulty, and supported engine. The UI shows the generation report and each question's engine. The backend currently generates synchronously, does not filter by requested question type, and does not return some list metadata such as creation time or last score. The UI labels those limitations rather than inventing values.

Question responses used by the player do not contain correct answers. The answer key is used only after submission, on the results screen. The player remembers answers in component memory and attempts to save them in session storage; if storage is unavailable, the attempt still works in memory.

Choosing the AI provider sends document text to an online service. Private documents disable that choice. Because the current document API does not include the privacy flag, the frontend also disables the online option when privacy cannot be verified. The backend independently falls back to its offline engine for private material.

The flashcard review screen flips each card to reveal its grounded answer and source page, then sends Again, Hard, Good, or Easy to the backend. The backend returns the next interval when available.

## Key syllabus concept

Flashcard review demonstrates spaced repetition: each rating changes when the fact is scheduled next. Quiz source links and explanations support retrieval practice with evidence from the original document.

## Viva questions and answers

1. **What is active recall?**  
   Trying to retrieve an answer from memory before looking at it.

2. **Why are quiz answers hidden during an attempt?**  
   Showing them early would reveal the answer and invalidate the learner's attempt.

3. **What does a partial quiz-generation result mean?**  
   The backend accepted fewer validated questions than requested; the UI reports the returned count and any engine fallback without pretending the request fully succeeded.

4. **What is spaced repetition?**  
   Scheduling future reviews at intervals that depend on how well a learner recalls a card.

5. **Why does the AI-provider option explain where text goes?**  
   It makes the privacy consequence clear before document text is sent to an online service.
