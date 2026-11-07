# Step 14a: Student analytics

## What was built

The backend now reports quiz score history, topic accuracy, weak topics, estimated study time, study streaks, flashcard retention, and a summary of the main progress numbers. Each endpoint requires authentication and only reads the signed-in student's records.

Quiz submissions update `topic_stats` using the source chunk's section or matching key term. Accuracy is stored as a fraction alongside answered and correct counts, plus the time the topic was last seen. The first submission completes and counts an attempt; later submissions return its saved results without changing the statistics. This keeps the existing study planner's section-based topic estimates working.

## Why and how it works

Analytics are calculated from the existing quiz attempts and answers, flashcard review logs, cards, and user chat messages. No language model or cache is involved. Empty accounts receive valid empty chart series and zero-valued summary numbers.

Weak topics have at least three answered questions and accuracy below a request-configurable threshold (60% by default). They are sorted by lowest accuracy, then most answers. Their response includes source document IDs and pages.

Study-time estimates sum recorded quiz elapsed time, a configurable number of seconds per flashcard review (30 seconds by default), and an estimated five minutes per user chat message by default. These estimates are labeled in the response; chat time is approximate because the application does not record reading or thinking time.

Streaks count each local calendar day once, even when several activity types occur that day. The current streak includes activity today or yesterday; the longest streak considers all recorded activity. Dates use the user's IANA timezone, which defaults to UTC. Flashcard retention reports the weekly share of reviews rated Good or Easy; mature cards have an interval of at least 21 days, and new cards have no successful repetitions.

## Key syllabus concept

Learning analytics turn interaction history into feedback a learner can act on. Topic-level accuracy can guide revision, while streaks and retention summarize consistency and spaced-repetition outcomes. These measures describe observed activity; they do not prove mastery or precisely measure study time.

## Viva questions

1. **What is learning analytics?**
   It is the analysis of learner activity and performance data to support progress monitoring and study decisions.

2. **How is a weak topic identified here?**
   A topic needs at least three answered questions and accuracy below the selected threshold, which defaults to 60%.

3. **Why use a user's timezone for streaks?**
   A study day should follow the learner's local calendar rather than UTC boundaries.

4. **How is flashcard retention calculated?**
   For each week, it is Good and Easy reviews divided by all reviews, expressed as a percentage.

5. **Why is study time labeled as an estimate?**
   Quiz duration is recorded, but flashcard and chat effort are inferred from configured activity assumptions rather than directly timed.
