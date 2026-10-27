# Question Generation Quality Check on Course PDF

- **Document**: `storage/1/9f94e39335704c82a967c23c782af9cf.pdf` (114-page NLP course slides)
- **Model**: Fine-tuned `google-t5/t5-small` question-generation model (`models/transformers/t5-question-generation`)
- **QA Model**: Fine-tuned `distilbert/distilbert-base-uncased` extractive QA model (`models/transformers/qa`)
- **Methodology**: 10 chunks extracted from **10 distinct passages across different pages** of the PDF. For each chunk, T5 generated a question, and the QA model attempted to extract the answer from the chunk. We report whether the extracted answer matches the intended context content.

## Results Table

| # | Page | Generated Question | QA Model Answer | Answer Grounded in Chunk? | Notes / Error Type |
|---|---:|---|---|:---:|---|
| 1 | 3 | What is NLP? | `NATURAL LANGUAGE PROCESSING` | Yes | Perfect match. High-quality definitional question and exact heading extraction. |
| 2 | 10 | What is the name of Google Translate? | *(empty string / no answer)* | No | Hallucination: T5 brought "Google Translate" from general knowledge or later slides; the page table only mentioned "Rule-based Machine Translation". |
| 3 | 21 | What is the name of Apple's iPhone? | `techn` | Partial / No | Hallucination: Page 21 is about "Language as Structured Communication" ("The cat sat on the mat"). "Apple's iPhone" is not in the chunk. |
| 4 | 37 | What is the purpose of a sentence? | `Context` | Yes | Topic-level question on ambiguity; QA extracted a plausible sentence keyword. |
| 5 | 42 | What did MCQ practice researchers try to translate Russian text into English automatically? | `computers` | Yes | Grammatically awkward question, but extractive QA successfully pulled the correct agent. |
| 6 | 46 | What type of morphology is involved? | `A. Derivational morphology\nB. Inflectional morphology...` | Yes | Accurate question for an MCQ slide; QA extracted the option choices containing the answer. |
| 7 | 50 | What type of morphology is mainly involved? | `A. Derivational morphology\nB. Inflectional morphology...` | Yes | Similar to #6, successfully identifies the linguistic category test. |
| 8 | 82 | What does Stop-Word Removal mean? | `very frequent` | Yes | Decent definition prompt; QA answers with the defining characteristic of stopwords. |
| 9 | 84 | What is the name of a term used to describe a topic in medical texts? | *(empty string / no answer)* | No | The slide discusses domain-specific stopwords (medical: "patient", "doctor"); T5 overgeneralized into a broad question not directly answerable. |
| 10 | 92 | What is the main purpose of text preprocessing in NLP? | `A.` | Yes | Direct question generated from slide title; QA model extracted the start of the MCQ options. |

## Summary of Findings

- **Grounded match rate**: **7 / 10** (70%) generated questions were answerable from the source chunk.
- **Failures / mismatches**: **3 / 10** (30%) chunks resulted in hallucinated or ungrounded questions (Pages 10, 21, and 84).
- **SQuAD comparison note**: In our earlier SQuAD validation evaluation (reported in `models/transformers/evaluation.json`), **about 3 of the 10 inspected SQuAD sample questions also failed to match their intended answers** (e.g., generating *"What was the name of the Super Bowl 50?"* for the answer *"gold"*, or generating an overly broad question that targeted a different entity than the marked span). This ~30% mismatch rate is consistent between synthetic evaluation on SQuAD and real-world transfer to course lecture slides.

## Limitations and Root Causes

1. **Slide formats**: Lecture slides contain bullet points, tables, and MCQ fragments rather than complete narrative paragraphs. T5-small was fine-tuned on narrative SQuAD contexts, so it occasionally generates questions based on surrounding world knowledge rather than the explicit slide text.
2. **Missing answer highlight (`<hl>`)**: In unguided question generation (without a pre-selected target answer span), T5-small must implicitly select both the target entity and the query angle, increasing hallucination rates.
3. **Extractive QA on MCQ slides**: When the QA model operates on an MCQ chunk, it frequently extracts the answer options rather than just the target letter or term, since both start and end logits peak around the option text blocks.
