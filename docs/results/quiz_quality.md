# Quiz quality report

Document: nlp_notes.pdf (id 2); private: False
Indexed chunks: 199; sampled pages [3, 103] across 2 sections.
Each LLM request asks for up to 3 outputs; the LLM request budget is 8.
Duplicate outputs are reported separately and excluded from validation-attempt counts.
Private text is never sent to an LLM provider. Both engines use the local QA round-trip check.

## classic

- Chunks sampled: 2
- Candidate outputs: 2
- Validation attempts (duplicates excluded): 2
- Duplicate outputs: 0
- Accepted: 2; rejected: 0
- Pass rate: 100.0%
- Requests used: 0
- Rate limited: no
- Questions returned: 2
- Provider answers: `{}`
- Provider responses: `{}`
- Question type mix (returned): `{}`
- Round-trip failures: 0
- LLM parse failures: 0
- Rejection/error counts: `{"accepted": 2}`
- Accepted chunks/pages: 1 chunks; 1 pages
- Accepted by type: `{"fill_in_the_blank": 2}`
- Accepted true/false counts: True 0, False 0
- Final true/false balance: N/A (no true/false questions)

### Accepted examples
- p.3 (chunk 5): Fill in the blank: NLP is the translator between _____. -> these two worlds (readability 1.00)
- p.3 (chunk 5): Fill in the blank: NLP is the branch of AI concerned with giving computers the ability to understand, interpret, and generate _____ in a valuable way. -> human language (readability 1.00)

### Rejected examples
- No question candidates were rejected in this run.

## Pages 20-30 classic quiz check

Accepted: 0 questions from 12 chunks.
only 0 passed; use the LLM engine.

Questions (LLM first, classic fallback):

## llm

- Chunks sampled: 2
- Candidate outputs: 6
- Validation attempts (duplicates excluded): 6
- Duplicate outputs: 0
- Accepted: 3; rejected: 3
- Pass rate: not measurable (<20 questions returned)
- Requests used: 2
- Rate limited: no
- Questions returned: 6
- Provider answers: `{"groq": 6}`
- Provider responses: `{"groq": 2}`
- Question type mix (returned): `{"fill_in_the_blank": 2, "multiple_choice": 1, "short_answer": 1, "true_false": 2}`
- Round-trip failures: 2
- LLM parse failures: 0
- Rejection/error counts: `{"accepted": 3, "round_trip_failed": 2, "stem_not_single_sentence": 1}`
- Accepted chunks/pages: 2 chunks; 2 pages
- Accepted by type: `{"fill_in_the_blank": 1, "true_false": 2}`
- Accepted true/false counts: True 0, False 0
- Final true/false balance: 0.0% True

### Accepted examples
- p.3 (chunk 5): Fill in the blank: NLP is the branch of AI concerned with giving computers the ability to understand, interpret, and generate human language in a ____ way. -> valuable (readability 1.00)
- p.3 (chunk 5): True or False: Humans communicate in messy, context-dependent ways. -> True (readability 1.00)
- p.103 (chunk 153): True or False: The regex \d+ matches one or more letters. -> False (readability 1.00)

### Rejected examples
- p.3 (chunk 5, round_trip_failed): What does NLP act as between humans and computers? -> translator (readability 1.00)
- p.103 (chunk 153, stem_not_single_sentence): Fill in the blank: The method text.lower() is used to _____ the text. -> convert to lowercase (readability 1.00)
- p.103 (chunk 153, round_trip_failed): What does text.translate(str.maketrans('', '', string.punctuation)) do? -> Removes punctuation symbols (readability 1.00)

## Notes

- Pass rates are automated validation rates, not a human rating of pedagogical quality.
- LLM parse failures count each invalid response, including the strict retry; failed LLM outputs are not relabeled as classic.
- A provider error or private source yields an unavailable LLM rate rather than a fallback score.
- Up to ten accepted and ten rejected examples are included per engine; fewer appear when fewer passed through that path.
