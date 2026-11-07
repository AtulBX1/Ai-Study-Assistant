# Step 16a: Chat and PDF Viewer

## What we built

The study screen pairs a document-grounded chat with a PDF viewer. Students can change answer style and language, stop a response, and follow a citation to its page.

## Why it matters

Reading source material and asking questions about it are most useful when they stay connected. A citation can take a student from an explanation directly to the page that supports it.

## How it works

- The document picker uses the typed API client. A study screen creates a chat session when the first question is sent and sends only the fields supported by the chat endpoint: the question, answer mode, language, and document ID.
- The backend sends SSE `data:` events containing JSON token objects followed by a `done` object. The authenticated `useSSE` helper makes a POST request, refreshes the session after a 401, and aborts when the student stops or leaves the stream.
- PDF.js is dynamically loaded in the browser. The original PDF is fetched through the authenticated download endpoint as a blob; the worker is bundled from `pdfjs-dist`, and pages are rendered only as they approach the viewport. A text layer keeps page text selectable. If the PDF cannot render, the viewer requests its authenticated page-image endpoint.
- Markdown is rendered as React text and elements rather than injected HTML. Links are limited to safe protocols, code blocks and lists remain readable, and citations become buttons that navigate the viewer.
- Chat mode and answer language are supported server parameters. The current chat API has no retrieval or reranking controls; it always uses hybrid retrieval and attempts reranking, so the interface reports that behavior instead of submitting unsupported values.
- Only the split-pane position is saved as a UI preference, and storage access is guarded. Chat messages and session IDs remain in memory.

## Key syllabus concept

Retrieval-augmented generation (RAG) connects a generated answer to retrieved evidence. Streaming over Server-Sent Events delivers the answer incrementally while page citations keep the generated text traceable to its source.

## Viva questions

1. **Why does the chat use Server-Sent Events?**
   SSE is a simple one-way channel for sending answer tokens from the server to the browser as they are generated.
2. **Why does the stream use `fetch` instead of `EventSource`?**
   The app must attach a bearer token, send a JSON POST body, refresh authentication, and abort the request.
3. **Why load PDF.js only in the browser?**
   PDF.js uses browser APIs, canvas, and a web worker that are not available during server-side rendering.
4. **How does the text layer help?**
   It positions extracted PDF text over the rendered page so the student can select and copy text.
5. **How are untrusted answers rendered safely?**
   Markdown is converted into React elements without raw HTML injection, and link URLs are restricted to safe protocols.
