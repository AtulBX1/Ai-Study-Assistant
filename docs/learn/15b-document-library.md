# Step 15b: Document Library

## What we built

The Library lets a student add PDFs, see upload and processing status, find their documents, and open a detail page with key terms and extracted page previews. A profile section in Settings lets a student update their public handle and leaderboard visibility.

## Why it matters

The library is the starting point for studying from a user's own course material. Upload progress makes large files feel responsive, while status updates explain when extraction and indexing are finished. The detail page keeps each term and preview tied to its source document.

## How it works

- The browser checks the PDF type, duplicate selection, and 20 MB limit before uploading. It also makes a best-effort local count of PDF page objects; the backend remains authoritative for its 500-page limit.
- Uploads use `XMLHttpRequest` so the interface can show byte progress and cancel an active transfer. A `401` triggers one session refresh and one retry.
- The status hook listens to the authenticated SSE endpoint. If the stream errors or closes before the document reaches a terminal state, it polls the status endpoint with increasing delays. It stops on `ready`, `failed`, or component unmount.
- The library uses backend limit/offset pagination and filters/sorts the documents already loaded. Page previews are fetched in small batches when the Pages tab is opened.
- The current backend upload and response schemas have no document privacy field or privacy-update endpoint. The interface therefore prevents sending an item while its default-on Private checkbox is selected and explains that unchecking it sends a non-private upload. Privacy state is shown as unavailable rather than implied to have been saved.
- Profile settings use the backend profile endpoints and display validation/cooldown errors without exposing email publicly.
- Vitest and Playwright cover this work with mocked API responses; no test requires a running backend.

## Key syllabus concept

The library makes document ingestion observable: raw PDF content is extracted and indexed before downstream NLP features can retrieve terms or pages. The UI presents those asynchronous processing stages while preserving the original document as the source for later answers.

## Viva questions

1. **Why use `XMLHttpRequest` for uploads?**
   It exposes upload progress events and supports aborting a transfer.
2. **Why is SSE consumed with `fetch` instead of `EventSource`?**
   `fetch` permits the app to attach its bearer authorization header.
3. **Why does the UI poll after an SSE failure?**
   Polling provides a bounded fallback when a stream disconnects before a terminal status arrives.
4. **Why is local page counting only best effort?**
   PDFs can be compressed or structured in ways that make simple text matching unreliable; the server must enforce its page limit.
5. **How does the interface handle the missing privacy API?**
   It blocks uploads while Private is checked and labels stored privacy as unavailable instead of pretending the backend persisted it.

## Security hardening note

The refresh token is currently stored in `localStorage` as a documented client-side trade-off. Moving it to an `httpOnly`, `Secure`, `SameSite` cookie is planned for the authentication hardening step.
