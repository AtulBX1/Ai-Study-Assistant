# Step 14b: Public tests, rankings, and anonymous handles

## What was built

Students can publish an owned quiz for admin review, browse approved public tests,
take shuffled attempts, and compare their results with the shared test pool. Public
test questions are copied into a snapshot, so changes to the original quiz cannot
change a published test. The snapshot keeps only question content and removes
source metadata such as evidence, page text, and document names.

Each account receives an anonymous public handle. A learner may change it once
every 30 days and can hide it from leaderboards. Hidden learners still contribute
anonymously to pool statistics. Public responses use handles only and never
include email addresses, real names, or account IDs.

## How ranking works

Only the learner's first completed attempt for a test is eligible. Attempts score
by percentage descending, then elapsed time ascending, then submission time. The
score percentile is the percentage of other ranked attempts below the learner,
plus half of the attempts tied on score. Later attempts are saved as practice and
do not change the pool.

Each test reports mean, median, population standard deviation, 10-point score bins,
and per-question accuracy. A pool below the configured minimum (10 by default)
withholds percentile and leaderboard rows. Per-topic comparisons use the same
ranked pool as the test.

## Fairness, privacy, and anti-cheating

The server stores attempt start times and enforces each test deadline. Answers
saved before the deadline remain eligible if the final submission is late; answers
first sent after the deadline are ignored. Correct answers and explanations are
returned only after submission. A single-use submission token prevents a second
submission.

Attempts faster than the configured minimum (3 seconds per question by default)
are marked suspicious and excluded from ranks and pool statistics. Starting and
reporting tests are rate limited, submissions have a daily cap, and three
different users reporting one test hide it for admin review.

Documents, chats, flashcards, private quizzes, private quiz attempts, and personal
analytics remain owner-only. Public tests are the only shared learning content.
The former teacher role and class tables have been removed.

## Viva questions and answers

1. **Why snapshot a quiz when it is published?**  
   A snapshot makes the public test stable even if its private source quiz changes.

2. **How is a score percentile calculated?**  
   It counts other ranked scores strictly below and half of scores tied with the
   learner, divided by the other ranked attempts.

3. **Why do hidden users still count in pool statistics?**  
   Hiding a handle controls public identity, not whether the learner's result
   contributes anonymously to fair aggregate statistics.

4. **How does the server handle a late submission?**  
   It marks the attempt late, keeps answers saved before the deadline, ignores
   answers first sent after it, and grades the retained answers.

5. **How does the system limit obvious speed-based cheating?**  
   It flags attempts below the configured seconds-per-question threshold and
   excludes them from rankings and aggregate pool statistics.
