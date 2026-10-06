# Step 3: PDF upload and ingestion

## What was built

Authenticated users can upload PDFs, check progress, stream status changes, list
and retrieve their own documents, read extracted page content, view rendered
page images, download the original file, and delete documents. Uploads are
checked from their content, bounded by configured file-size and page limits,
and stored through the `FileStorage` interface. SQLite remains the local
development database; the local `JobQueue` runs ingestion as a FastAPI
background task.

The ingestion worker stores each page's text, detected headings, extracted
tables, and OCR result marker. It reports the `queued`, `extracting`,
`processing`, `indexing`, `ready`, or `failed` state with percentage progress
and an error message when applicable. The `indexing` state is currently a
placeholder for future chunking and embeddings.

## Why it was built

PDF contents must be converted into page-addressable evidence before later
search and question answering can cite the source document and page. Keeping
page boundaries, layout hints, tables, and OCR state makes that later retrieval
more useful and makes extraction failures visible instead of silently treating
scanned pages as empty.

## How it works

1. **Upload and validation:** the API reads at most the configured limit plus
   one byte, recognizes the PDF signature in the content, and opens the file
   with PyMuPDF to reject corruption, encryption, empty documents, and excess
   pages. It sanitizes the display filename and creates a generated,
   owner-scoped storage key. The file and queued document/status event are
   persisted before a job is sent through `JobQueue`.
2. **Text and layout extraction:** PyMuPDF reads text separately for each
   1-based page. Font sizes and bold flags identify lines that appear to be
   headings. These heuristics preserve layout clues; they do not guarantee
   perfect semantic section boundaries.
3. **Tables and OCR:** pdfplumber extracts structured cell rows and the worker
   also appends a readable table rendering to that page's text. Pages with
   fewer than 40 non-whitespace extracted characters are rendered and passed
   to Tesseract. If the Tesseract executable is missing, the page is still
   saved with `ocr_unavailable` and the rest of the document proceeds.
4. **Background job and progress:** the worker records status transitions and
   progress events in the database. Local development uses FastAPI
   `BackgroundTasks`; the production adapter dispatches the named job to
   Celery. The future indexing stage is intentionally a no-op.
5. **Live status (SSE):** `GET /documents/{id}/events` replays persisted events
   as Server-Sent Events and follows new updates until the job reaches a
   terminal state. The regular status endpoint exposes the latest state,
   progress percentage, and error message.

Every document lookup is constrained by the authenticated owner, including
status, page, image, download, event, and delete routes. Extracted PDF text is
untrusted data: it is stored as source content, not interpreted as instructions.
Consumers must keep it separate from trusted prompts and cite the source page.
Rendered page images are held in a bounded in-process cache.

Configure `MAX_PDF_SIZE_BYTES` and `MAX_PDF_PAGES` in the environment to adjust
the upload limits. Tesseract is an optional system executable; installing the
Python wrapper alone does not provide OCR.

## Key syllabus concept

This step prepares document data for NLP: page text is extracted into a usable
text representation, while font/layout evidence and table structure retain
context that plain text alone can lose. OCR provides a text-processing path for
image-only pages.

## Viva questions

1. **Why validate a PDF by content instead of trusting its filename?**  
   A filename and MIME type are supplied by the client and can lie. Content
   sniffing and opening the bytes verifies that the upload is actually a
   readable PDF.

2. **Why keep text and page numbers together?**  
   Page-level storage preserves provenance so later answers and search results
   can point to the exact source page.

3. **How does heading detection work here?**  
   It compares each text line's font size with the page's typical font size and
   also considers bold font flags to identify likely headings.

4. **What happens when a page is scanned and Tesseract is unavailable?**  
   The worker stores the page with an `ocr_unavailable` marker and continues
   processing the remaining pages instead of failing the document.

5. **Why persist status events for Server-Sent Events?**  
   A client can reconnect or subscribe after a fast background job has already
   advanced, and the persisted event history allows it to receive the missed
   transitions.
