# Step 16b: Grounded chat UI

## What was built

The study screen now shows how well an answer is grounded, highlights cited text in the PDF when it can be found, and explains which retrieved passages support an answer. Students can rate answers, revisit chats, and use browser speech controls.

## Evidence and trust signals

The chat stream sends a final event containing `message_id`, `grounding_score`, `unsupported_sentences`, and `explanation`. The saved message API returns the same fields, so the interface can restore the badges and feedback after a reload. The badge uses three labelled levels: well supported (0.75 or higher), partly supported (0.50 to below 0.75), and weakly supported (below 0.50). The exact score is available in its tooltip and accessible label. Backend-flagged unsupported sentences are underlined and described as “Not found in your document.”

The answer explanation includes retrieved chunks, answer lines used by the pipeline, provider, answer mode, and latency. Each chunk has its page, section, retrieval score, and rerank score. The pipeline uses hybrid retrieval; the drawer shows that mode and lazy-loads the saved explanation when opened. Retrieval and grounding scores are different: retrieval ranks candidate passages, while grounding evaluates the generated answer against those passages.

When retrieval refuses to answer with “not found in the document,” the interface uses a separate visual state and offers a way to rephrase or focus the document switcher.

## Citation matching

The PDF.js text layer is searched after a citation selects its page. Matching ignores letter case, collapses whitespace, and joins a word split by a line-ending hyphen. If the full normalized passage is absent, the matcher looks for the longest consecutive run of at least eight words shared by the evidence and page text. A range over the matching text nodes provides the highlight rectangles. The PDF viewer scrolls the passage into view; if it cannot find selectable text, it still selects the page and displays the quoted source passage above the viewer.

This is matching against extracted PDF text, not image recognition. A scanned page or OCR differences may therefore show the source banner instead of a highlight.

## Browser speech and privacy

Speech recognition and read-aloud use the browser’s SpeechRecognition and speechSynthesis APIs. The language follows the answer-language choice: `en-US`, `hi-IN`, or `pa-IN`. Speech output removes markdown and citation labels before speaking, and selects a matching browser voice when one is available. If a browser does not provide an API, its control is hidden.

Speech recognition runs in the browser and is not sent to this app’s server. Some browsers may transmit recognition audio to the browser vendor’s servers; the UI explains this before first use. Microphone permission errors are shown to the student.

## Chat history and feedback

Chat history is loaded from the chat-session endpoints, with message evidence used to associate saved sessions with the current document. The UI paginates the returned list and confirms deletion. Since the current backend contract has no rename or document-filter/pagination endpoint, renamed titles are stored in browser local storage and the UI filters/paginates the available sessions locally.

Thumbs-up and thumbs-down feedback use the backend’s `/chat/messages/{message_id}/feedback` endpoint. A thumbs-down dialog can include a reason. The stored feedback and reason come back with the saved message; once saved, feedback controls are disabled to prevent repeat submissions.

## Viva questions

1. **What does a grounding score tell us?**  
   It estimates whether an answer is supported by retrieved document evidence. It is not the same as the retrieval score.

2. **Why does citation matching normalize text?**  
   PDF text extraction may change spaces, line breaks, letter case, or split a word with a line-ending hyphen. Normalization lets the UI find the same passage despite those formatting differences.

3. **When does fuzzy matching highlight a passage?**  
   When the exact normalized sentence is absent, it highlights the longest common consecutive word run of at least eight words.

4. **How is the “Why this answer” explanation grounded?**  
   It reads the saved explanation data produced by the RAG pipeline: retrieved chunk text and scores, answer lines, provider, mode, and latency.

5. **What is the privacy limitation of browser speech recognition?**  
   Audio stays out of this application’s server requests, but some browser vendors may process speech-recognition audio on their own servers.
