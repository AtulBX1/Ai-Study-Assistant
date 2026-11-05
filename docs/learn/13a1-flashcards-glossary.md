# Step 13a-1: Flashcards and Glossary

## What we built

The study API now creates review cards from accepted fill-in-the-blank and
"what" quiz questions, plus terms in a document glossary. Cards retain their
document deck, source page, and exact evidence sentence. A grounded glossary
uses only saved key terms, NER entities, and keyphrases; its definitions come
from sentences already stored for the source page. There is no LLM definition
generation.

## Why

Review scheduling helps students revisit material at useful intervals. The
page and evidence sentence make it possible to check every generated card and
definition against the source rather than relying on an unsupported guess.

## How it works

An authenticated user can regenerate a glossary, add or rename a custom term
that appears in a page, generate cards for a document, review or suspend cards,
and list due cards and deck statistics. Data queries are scoped to the signed-in
owner. Repeated card generation uses a stable fact key to avoid duplicates.

Review ratings map to SM-2 quality values: Again 0, Hard 3, Good 4, and Easy 5.
The scheduler updates ease, repetition count, interval, and due date, and
stores every rating in the review log.

## Syllabus concept

Spaced repetition is a learning strategy that schedules review over increasing
intervals. SM-2 adjusts each interval based on how well a learner recalls a
card. Grounded glossaries connect a term to evidence in the source text.

## Viva questions

1. **What does SM-2 do?** It uses a review quality rating to update a card's
   ease, repetition count, and next review interval.
2. **What does a Good rating do for a new card?** It schedules the first review
   one day later; the next Good review is scheduled six days later.
3. **Why store an evidence sentence and page?** They let a learner verify that a
   card or definition is supported by the document.
4. **How does the glossary avoid unsupported definitions?** It selects a
   defining sentence, or the best sentence containing the term, from stored
   page text; it does not call an LLM.
5. **How are user materials kept private?** Every read, write, and review query
   is constrained by the authenticated owner's ID.
