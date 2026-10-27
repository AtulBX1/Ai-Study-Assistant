# Step 11b chat grounding calibration

- PDF: `data/real_docs/nlp_notes.pdf` (10,201,609 bytes).
- Questions: 30 generated from extracted PDF sentences; 15 fixed out-of-domain questions.
- Retrieval refusal threshold: `-10.4715` (top cross-encoder score; missing score refuses).
- In-document false-refusal rate: 0/30 (0.0%).
- Out-of-document refusal accuracy: 14/15 (93.3%); missed refusals: 1.
- In-document answer grounding distribution (sentence-level supported fraction): min 0.00, Q1 0.00, median 1.00, Q3 1.00, max 1.00.

## Notes and limitations

Questions are deterministic templates, not human-authored or independently verified labels; in-document expected answers are the source sentences. The out-of-domain set is not an exhaustive test of the document topic boundary. This small run is a diagnostic, not a statistically reliable threshold estimate.
The threshold compares the reranker's raw score (not a calibrated probability); its scale depends on the local cross-encoder. Candidate chunks are prefiltered by simple lexical overlap before cross-encoding, not by the full production hybrid retriever. The selected threshold is specific to this synthetic question set and must not be treated as a general accuracy claim.
The cached local cross-encoder was available and used; no network access was requested.
Grounding is a lightweight sentence embedding plus keyword-overlap heuristic; it can miss paraphrases and logical contradictions. A score is not a truth guarantee.

## Per-question diagnostic

| Set | Question | Rerank score | Refused | Grounding | Unsupported |
|---|---|---:|:---:|---:|---|
| in | What does the document state about Bag-of-Words? | 0.0525 | no | 1.00 |  |
| in | What does the document state about following? | -9.2000 | no | 1.00 |  |
| in | What does the document state about continuous? | -10.2903 | no | 0.00 | A stop-word list Correct Answer: B An N-gram is a continuous sequence of N items from text. |
| in | What does the document state about meanings? | -6.7779 | no | 1.00 |  |
| in | What does the document state about following? | -9.2000 | no | 0.00 | MCQ Practice • Consider the following changes: • cat → cats • happy → happiness Which statement is correct? |
| in | What does the document state about generalization? | -10.4189 | no | 1.00 |  |
| in | What does the document state about context-dependent? | -1.9018 | no | 1.00 |  |
| in | What does the document state about PREPROCESSING? | 2.4826 | no | 1.00 |  |
| in | What does the document state about fine-tuning? | -4.0616 | no | 1.00 |  |
| in | What does the document state about represents? | -7.1192 | no | 0.00 | It captures word meaning Correct Answer: C BoW represents text using word counts and ignores grammar and order. |
| in | What does the document state about following? | -9.2000 | no | 1.00 |  |
| in | What does the document state about contextual? | -4.6447 | no | 1.00 |  |
| in | What does the document state about Punctuation? | -5.1184 | no | 1.00 |  |
| in | What does the document state about dimensionality? | -8.8600 | no | 1.00 |  |
| in | What does the document state about Punctuation? | -5.1184 | no | 0.00 | ; : " ' ( ) •Commonly done using NLTK (Natural Language Toolkit) in Python Why Do We Remove Punctuation? |
| in | What does the document state about distinguishing? | -9.5993 | no | 0.00 | Because TF-IDF uses binary features Correct Answer: C TF-IDF penalizes common words since they contribute less to distinguishing documents. |
| in | What does the document state about Context-dependent? | -1.9018 | no | 1.00 |  |
| in | What does the document state about document? | -7.8323 | no | 1.00 |  |
| in | What does the document state about training? | -9.1361 | no | 1.00 |  |
| in | What does the document state about contribute? | -9.9332 | no | 1.00 |  |
| in | What does the document state about memory-efficient? | -10.4037 | no | 0.00 | Reduces Vocabulary Size Prevents unnecessary tokens Makes models: Faster, More memory-efficient, Easier to train 5. |
| in | What does the document state about WordNetLemmatizer? | -4.0849 | no | 1.00 |  |
| in | What does the document state about Example? | -4.6628 | no | 1.00 |  |
| in | What does the document state about grammatical? | -8.5935 | no | 0.00 | MCQ Practice • An NLP system processes the words “cat,” “cats,” “walk,” and “walked.; ” It notices that the words change to express grammatical information such as number or tense. |
| in | What does the document state about Bag-of-Words? | 0.0525 | no | 1.00 |  |
| in | What does the document state about Punctuation? | -5.1184 | no | 1.00 |  |
| in | What does the document state about stopword? | -1.9392 | no | 1.00 |  |
| in | What does the document state about ambiguous? | -6.6285 | no | 1.00 |  |
| in | What does the document state about identifies? | -8.9923 | no | 0.00 | MCQ Practice • An NLP system sees the sentence: “The children played in the park.; ” It identifies that children expresses plural meaning and played expresses past tense. |
| in | What does the document state about Preprocessing? | 2.4826 | no | 1.00 |  |
| out | What is the orbital period of Saturn's moon Enceladus? | -11.2560 | yes | 0.00 | not found in the document |
| out | What is the chemical formula of hemoglobin? | -10.8967 | yes | 0.00 | not found in the document |
| out | How many moons orbit the planet Mars? | -11.2466 | yes | 0.00 | not found in the document |
| out | What is the boiling point of liquid nitrogen? | -11.2228 | yes | 0.00 | not found in the document |
| out | Who won the 2018 FIFA World Cup? | -10.4715 | yes | 0.00 | not found in the document |
| out | What is the deepest point in the Pacific Ocean? | -11.1522 | yes | 0.00 | not found in the document |
| out | How does a nuclear fusion reactor confine plasma? | -11.1256 | yes | 0.00 | not found in the document |
| out | What is the mass of the Andromeda galaxy? | -11.2369 | yes | 0.00 | not found in the document |
| out | Which enzyme replicates DNA in human cells? | -10.2396 | no | 0.00 | not found in the document |
| out | What is the exchange rate of the euro today? | -11.3235 | yes | 0.00 | not found in the document |
| out | When did the first powered flight cross the Atlantic? | -11.2173 | yes | 1.00 |  |
| out | What is the population of Kyoto this year? | -11.2780 | yes | 0.00 | not found in the document |
| out | How many rings does Uranus have? | -11.1987 | yes | 0.00 | not found in the document |
| out | What is the melting point of tungsten? | -11.1990 | yes | 0.00 | not found in the document |
| out | Which tectonic plate contains the Hawaiian Islands? | -10.9448 | yes | 0.00 | not found in the document |
