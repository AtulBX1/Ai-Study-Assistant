# Step 13b-2: Multi-document tools and exports

## What we built

The study service can answer a question using several of the signed-in user's
documents, compare two documents, and export study materials as PDF, DOCX, or
CSV. Cross-document question requests are limited by
`MAX_MULTI_DOCUMENT_COUNT` (five by default). The API checks document ownership
before retrieval or generation.

## Why it is useful

Students can ask one question across several sources, see which document and
page support an answer, compare overlapping topics, and download notes or
other study material for offline use. Private documents stay on the local
extractive answer path and are not sent to an external provider.

## How it works

Cross-document Q&A passes the selected document IDs to the existing chat
pipeline. That pipeline performs hybrid retrieval and reranking, builds
document-title/page citations, applies its grounding checks, and uses its
existing provider chain. The comparison tool needs no LLM: it compares stored
key terms and glossary entries, embeds stored sections, greedily matches
similar sections, and cites page ranges in each rule-based bullet.

The download endpoint reads owned study records and creates the requested file
in memory. DOCX preserves Unicode text; the PDF uses ReportLab's built-in font
and visibly marks characters it cannot render. Glossaries and study plans use
tables. Flashcards use UTF-8 CSV with the columns `front`, `back`, and `page`.
Exports are generated on demand and do not require a database migration.

## Key syllabus concept

Document similarity uses sentence embeddings: each section is encoded as a
vector, then cosine similarity estimates how closely two sections discuss the
same content. This complements lexical matching because similar concepts can
use different words. The resulting scores are only evidence of similarity;
the comparison's page references still point back to stored source sections.

## Viva questions and answers

1. **What is hybrid retrieval?**
   It combines sparse keyword matching with dense embedding retrieval so both
   exact terms and related meanings can locate relevant passages.

2. **Why rerank retrieved passages?**
   A reranker examines each query-passage pair and can move the most relevant
   evidence above passages that only matched a few keywords.

3. **How is cosine similarity used in document comparison?**
   It compares the direction of two section vectors; a larger score indicates
   that the sections have more similar embedding representations.

4. **Why do answers include a document title as well as a page?**
   Page numbers alone are ambiguous when evidence comes from more than one
   source. A title-plus-page citation identifies both the source and location.

5. **How does the exporter handle text that the PDF font cannot render?**
   It replaces unsupported characters with a visible `[?]` marker and adds a
   note to the PDF. DOCX retains the original Unicode text.
