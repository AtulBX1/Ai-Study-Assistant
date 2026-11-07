# Step 13b-1: Concept graphs and study planning

## What was built

The study API can make a small concept graph from stored key terms, named
entities, glossary terms, and the text already saved for a document. It can
also make and save a day-by-day study plan for selected documents.

## Why it is useful

A graph makes connections between important ideas visible. A study plan turns
large chapters into manageable daily work and gives difficult or weak topics
more attention.

## How it works

The graph service finds stored terms in page text. It recognizes simple
relationships such as “is a type of” and “uses.” When no such pattern occurs,
terms in the same sentence are connected as related. Every edge keeps the
original sentence and page as evidence. Nodes without an edge are omitted.
Optional relation labeling is disabled by default; private documents never
use a provider.

The planner segments stored pages into chapters or page blocks. It estimates
time from page count and difficulty labels, then adjusts priority using quiz
topic statistics when available. It schedules study first, adds review after
spaced intervals, keeps each day within its time budget, and reports topics
that did not fit. Plans and completion state are stored in the database.

## Syllabus connection

This feature demonstrates knowledge graphs and evidence-based relation
extraction from text. It also applies spaced revision: reviewing a topic after
increasing intervals helps organize repeated practice over time.

## Viva questions

1. **What is a concept graph?**

   A graph whose nodes represent concepts and whose edges represent
   relationships between those concepts.

2. **Why does each graph edge keep an evidence sentence?**

   The sentence lets a learner verify the relationship in the source material.

3. **How is a pattern relation different from co-occurrence?**

   A pattern relation uses explicit wording such as “uses”; co-occurrence only
   says that two concepts appear in the same sentence.

4. **What is spaced revision?**

   It schedules later reviews at intervals after first studying a topic.

5. **How does quiz performance affect the study plan?**

   A weak-topic score raises priority and study time so weaker areas are
   practiced earlier and more often.
