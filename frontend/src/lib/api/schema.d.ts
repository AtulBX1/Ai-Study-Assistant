export interface paths {
    "/auth/register": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Register
         * @description Create a student account and return its initial tokens.
         */
        post: operations["register_auth_register_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Public Profile
         * @description Return only the caller's public-facing profile settings.
         */
        get: operations["get_public_profile_auth_profile_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Update Public Profile
         * @description Update the public handle and/or leaderboard visibility.
         */
        patch: operations["update_public_profile_auth_profile_patch"];
        trace?: never;
    };
    "/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Login
         * @description Authenticate a user and issue an access/refresh token pair.
         */
        post: operations["login_auth_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/refresh": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Refresh
         * @description Rotate a valid refresh token and revoke its previous instance.
         */
        post: operations["refresh_auth_refresh_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Logout
         * @description Revoke a refresh token so it can no longer renew access.
         */
        post: operations["logout_auth_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/analytics/score-history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Score History
         * @description Return one dated score point per owned submitted attempt.
         */
        get: operations["get_score_history_analytics_score_history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/analytics/topic-accuracy": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Topic Accuracy
         * @description Return owner-scoped topic correctness, counts, and source pages.
         */
        get: operations["get_topic_accuracy_analytics_topic_accuracy_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/analytics/weak-topics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Weak Topics
         * @description List topics with three or more answers below the accuracy threshold.
         */
        get: operations["get_weak_topics_analytics_weak_topics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/analytics/study-time": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Study Time
         * @description Return estimated daily minutes over a bounded date window.
         */
        get: operations["get_study_time_analytics_study_time_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/analytics/streaks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Streaks
         * @description Return activity streaks using the learner's configured timezone.
         */
        get: operations["get_streaks_analytics_streaks_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/analytics/flashcard-retention": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Flashcard Retention
         * @description Return weekly review retention and due/mature/new card counts.
         */
        get: operations["get_flashcard_retention_analytics_flashcard_retention_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/analytics/summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Summary
         * @description Return headline quiz, topic, streak, and due-card measures.
         */
        get: operations["get_summary_analytics_summary_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/documents/upload": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Upload Document
         * @description Validate and store a PDF, then queue its page ingestion.
         */
        post: operations["upload_document_documents_upload_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/documents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Documents
         * @description Return a page of only the authenticated user's documents.
         */
        get: operations["list_documents_documents_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/documents/{document_id}/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Document Status
         * @description Return the owner-scoped current ingestion stage and progress.
         */
        get: operations["get_document_status_documents__document_id__status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/documents/{document_id}/rechunk": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Rechunk Document
         * @description Rebuild an owned document's chunks with the requested boundaries.
         */
        post: operations["rechunk_document_documents__document_id__rechunk_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/documents/{document_id}/reindex": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Reindex Document
         * @description Replace an owned document's vector points from its persisted chunks.
         */
        post: operations["reindex_document_documents__document_id__reindex_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/documents/{document_id}/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Stream Document Events
         * @description Stream persisted stage/progress updates until ingestion is terminal.
         */
        get: operations["stream_document_events_documents__document_id__events_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/documents/{document_id}/pages/{page_number}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Document Page
         * @description Return one page's text and structured layout from an owned document.
         */
        get: operations["get_document_page_documents__document_id__pages__page_number__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/documents/{document_id}/pages/{page_number}/image": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Document Page Image
         * @description Render and cache one owned PDF page as a PNG image.
         */
        get: operations["get_document_page_image_documents__document_id__pages__page_number__image_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/documents/{document_id}/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Download Document
         * @description Download the original PDF belonging to the authenticated user.
         */
        get: operations["download_document_documents__document_id__download_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/documents/{document_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Document
         * @description Fetch a document only when it belongs to the authenticated user.
         */
        get: operations["get_document_documents__document_id__get"];
        put?: never;
        post?: never;
        /**
         * Delete Document
         * @description Delete an owned document, its file, pages, chunks, and future vectors.
         */
        delete: operations["delete_document_documents__document_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/preprocess": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Preprocess
         * @description Return every requested preprocessing result for text or selected pages.
         */
        post: operations["preprocess_lab_preprocess_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/classify": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Classify Text
         * @description Classify text with the requested locally trained recurrent model.
         */
        post: operations["classify_text_lab_classify_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/summarize/seq2seq": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Summarize Seq2Seq
         * @description Summarize bounded text or pages belonging to the authenticated user.
         */
        post: operations["summarize_seq2seq_lab_summarize_seq2seq_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/seq2seq/results": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Seq2Seq Results
         * @description Return the latest locally stored held-out evaluation.
         */
        get: operations["seq2seq_results_lab_seq2seq_results_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/difficulty/batch": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Classify Document Chunks
         * @description Tag every chunk in an owned document with the saved difficulty classifier.
         */
        post: operations["classify_document_chunks_lab_difficulty_batch_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/ngrams": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Document Ngrams
         * @description Return per-page n-gram frequencies for an owned document.
         */
        get: operations["document_ngrams_lab_ngrams_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/tfidf-terms": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Document Tfidf Terms
         * @description Return a per-page BoW/TF-IDF view and the top terms for an owned document.
         */
        get: operations["document_tfidf_terms_lab_tfidf_terms_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/keyphrases": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Document Keyphrases
         * @description Extract ranked key terms or phrases from each page in an owned document.
         */
        get: operations["document_keyphrases_lab_keyphrases_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/word2vec/train": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Train Document Word2Vec
         * @description Train one owner-scoped CBOW or Skip-Gram model on document chunks.
         */
        post: operations["train_document_word2vec_lab_word2vec_train_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/embeddings/similar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Embeddings Similar
         * @description Return nearest terms, checking document ownership even for GloVe.
         */
        get: operations["embeddings_similar_lab_embeddings_similar_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/embeddings/similarity": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Embeddings Similarity
         * @description Return cosine similarity; local models require an owned document ID.
         */
        get: operations["embeddings_similarity_lab_embeddings_similarity_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/embeddings/analogy": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Embeddings Analogy
         * @description Solve a - b + c using a selected embedding vocabulary.
         */
        get: operations["embeddings_analogy_lab_embeddings_analogy_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/embeddings/compare": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Embeddings Compare
         * @description Show available Word2Vec and GloVe neighbours side by side.
         */
        get: operations["embeddings_compare_lab_embeddings_compare_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/embeddings/projection": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Embeddings Projection
         * @description Project frequent embedding terms and attach deterministic KMeans labels.
         */
        get: operations["embeddings_projection_lab_embeddings_projection_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/generate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Generate
         * @description Run selected greedy, beam, top-k, or top-p settings on local small GPT only.
         */
        post: operations["generate_lab_generate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/perplexity": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Perplexity
         * @description Compute next-token perplexity using the same local-only small GPT model.
         */
        post: operations["perplexity_lab_perplexity_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/search": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Search
         * @description Search only the current user's documents with a registered retriever.
         */
        post: operations["search_search_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/chat/sessions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Sessions
         * @description List all chat sessions belonging to the current user.
         */
        get: operations["list_sessions_chat_sessions_get"];
        put?: never;
        /**
         * Create Session
         * @description Create a new chat session owned by the authenticated user.
         */
        post: operations["create_session_chat_sessions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/chat/sessions/{session_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Session
         * @description Retrieve chat session and message history.
         */
        get: operations["get_session_chat_sessions__session_id__get"];
        put?: never;
        post?: never;
        /**
         * Delete Session
         * @description Delete a chat session and all its messages.
         */
        delete: operations["delete_session_chat_sessions__session_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/chat/sessions/{session_id}/messages": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Post Message
         * @description Post user question and stream the assistant's response via Server-Sent Events.
         */
        post: operations["post_message_chat_sessions__session_id__messages_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/chat/messages/{message_id}/feedback": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Submit Feedback
         * @description Submit thumbs up / down feedback with an optional reason.
         */
        post: operations["submit_feedback_chat_messages__message_id__feedback_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/quizzes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Quizzes */
        get: operations["list_quizzes_quizzes_get"];
        put?: never;
        /**
         * Create Quiz
         * @description Generate a bounded quiz from only the authenticated user's ready documents.
         */
        post: operations["create_quiz_quizzes_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/quizzes/{quiz_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Quiz */
        get: operations["get_quiz_quizzes__quiz_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/quizzes/{quiz_id}/questions/{question_id}/explanation": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Question Explanation
         * @description Return the explanation and owner-scoped source page link.
         */
        get: operations["question_explanation_quizzes__quiz_id__questions__question_id__explanation_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/quizzes/{quiz_id}/attempts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Start Attempt */
        post: operations["start_attempt_quizzes__quiz_id__attempts_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/quizzes/{quiz_id}/attempts/{attempt_id}/submit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Submit Answers */
        post: operations["submit_answers_quizzes__quiz_id__attempts__attempt_id__submit_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/quizzes/{quiz_id}/results/{attempt_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Results */
        get: operations["results_quizzes__quiz_id__results__attempt_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/quizzes/{quiz_id}/retake": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Retake */
        post: operations["retake_quizzes__quiz_id__retake_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/quizzes/{quiz_id}/exam.{format}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Exam */
        get: operations["exam_quizzes__quiz_id__exam__format__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/public-tests": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Public Tests
         * @description List only approved tests and return no private user information.
         */
        get: operations["list_public_tests_public_tests_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/public-tests/leaderboards/accuracy": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Global Accuracy Leaderboard */
        get: operations["global_accuracy_leaderboard_public_tests_leaderboards_accuracy_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/public-tests/me/overview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** My Public Test Overview */
        get: operations["my_public_test_overview_public_tests_me_overview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/public-tests/{test_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Public Test */
        get: operations["get_public_test_public_tests__test_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/public-tests/{test_id}/statistics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Public Test Statistics */
        get: operations["get_public_test_statistics_public_tests__test_id__statistics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/public-tests/{test_id}/leaderboard": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Public Test Leaderboard */
        get: operations["get_public_test_leaderboard_public_tests__test_id__leaderboard_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/public-tests/admin/tests/from-quiz": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Admin Create From Quiz */
        post: operations["admin_create_from_quiz_public_tests_admin_tests_from_quiz_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/public-tests/submissions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Submit Quiz For Publication */
        post: operations["submit_quiz_for_publication_public_tests_submissions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/public-tests/admin/queue": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Review Queue */
        get: operations["get_review_queue_public_tests_admin_queue_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/public-tests/admin/tests/{test_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Edit Test Metadata */
        patch: operations["edit_test_metadata_public_tests_admin_tests__test_id__patch"];
        trace?: never;
    };
    "/public-tests/admin/tests/{test_id}/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Moderate Test */
        patch: operations["moderate_test_public_tests_admin_tests__test_id__status_patch"];
        trace?: never;
    };
    "/public-tests/{test_id}/reports": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Report Test */
        post: operations["report_test_public_tests__test_id__reports_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/public-tests/{test_id}/attempts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Start Test Attempt */
        post: operations["start_test_attempt_public_tests__test_id__attempts_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/public-tests/{test_id}/attempts/{attempt_id}/answers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Save Test Answers */
        put: operations["save_test_answers_public_tests__test_id__attempts__attempt_id__answers_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/public-tests/{test_id}/attempts/{attempt_id}/submit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Submit Test Answers */
        post: operations["submit_test_answers_public_tests__test_id__attempts__attempt_id__submit_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/study/documents/{document_id}/flashcards/generate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Generate Flashcards
         * @description Create missing cards from accepted questions and the stored glossary.
         */
        post: operations["generate_flashcards_study_documents__document_id__flashcards_generate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/study/flashcards/due": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Due Flashcards
         * @description List only the authenticated user's unsuspended cards due by UTC midnight.
         */
        get: operations["list_due_flashcards_study_flashcards_due_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/study/flashcards/upcoming": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Upcoming Flashcard Counts
         * @description Count unsuspended cards by UTC due date over the next bounded number of days.
         */
        get: operations["upcoming_flashcard_counts_study_flashcards_upcoming_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/study/flashcards/{card_id}/review": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Review Flashcard
         * @description Schedule an owner-scoped card using its Again/Hard/Good/Easy rating.
         */
        post: operations["review_flashcard_study_flashcards__card_id__review_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/study/flashcards/{card_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Delete Flashcard
         * @description Delete an owner-scoped flashcard and its review history.
         */
        delete: operations["delete_flashcard_study_flashcards__card_id__delete"];
        options?: never;
        head?: never;
        /**
         * Set Flashcard Suspended
         * @description Suspend or resume an owner's flashcard.
         */
        patch: operations["set_flashcard_suspended_study_flashcards__card_id__patch"];
        trace?: never;
    };
    "/study/documents/{document_id}/flashcards/stats": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Flashcard Deck Stats
         * @description Return card, due, suspended, and review counts for one owned document.
         */
        get: operations["flashcard_deck_stats_study_documents__document_id__flashcards_stats_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/study/documents/{document_id}/glossary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Glossary Terms
         * @description Return a searchable, paginated glossary for an owned document.
         */
        get: operations["list_glossary_terms_study_documents__document_id__glossary_get"];
        put?: never;
        /**
         * Add Custom Glossary Term
         * @description Add a custom term only when its supporting sentence exists in the document.
         */
        post: operations["add_custom_glossary_term_study_documents__document_id__glossary_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/study/documents/{document_id}/glossary/regenerate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Regenerate Document Glossary
         * @description Regenerate glossary entries from persisted key terms without an LLM.
         */
        post: operations["regenerate_document_glossary_study_documents__document_id__glossary_regenerate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/study/glossary/{term_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Edit Custom Glossary Term
         * @description Rename an owner's custom term and refresh its grounded definition.
         */
        patch: operations["edit_custom_glossary_term_study_glossary__term_id__patch"];
        trace?: never;
    };
    "/study/documents/{document_id}/summaries": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Document Summaries
         * @description List summaries generated for an owned document.
         */
        get: operations["list_document_summaries_study_documents__document_id__summaries_get"];
        put?: never;
        /**
         * Create Summary
         * @description Generate or retrieve a grounded summary for an owned document.
         */
        post: operations["create_summary_study_documents__document_id__summaries_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/study/summaries/{summary_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Summary
         * @description Get a specific summary by ID.
         */
        get: operations["get_summary_study_summaries__summary_id__get"];
        put?: never;
        post?: never;
        /**
         * Delete Summary
         * @description Delete a summary by ID.
         */
        delete: operations["delete_summary_study_summaries__summary_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/study/summaries/jobs/{job_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Summary Job
         * @description Retrieve async summary job status.
         */
        get: operations["get_summary_job_study_summaries_jobs__job_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/study/documents/{document_id}/notes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Chapter Notes
         * @description Return rule-based chapter notes in Markdown.
         */
        get: operations["get_chapter_notes_study_documents__document_id__notes_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/study/documents/{document_id}/cheat-sheet": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Cheat Sheet
         * @description Return a rule-based one-page cheat sheet in Markdown.
         */
        get: operations["get_cheat_sheet_study_documents__document_id__cheat_sheet_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/study/documents/{document_id}/graph": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Document Graph
         * @description Return a bounded, owner-scoped graph with copied page evidence.
         */
        get: operations["get_document_graph_study_documents__document_id__graph_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/study/documents/{document_id}/graph/nodes/{node_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Graph Node
         * @description Return a graph node, its stored definition, and evidenced neighbours.
         */
        get: operations["get_graph_node_study_documents__document_id__graph_nodes__node_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/study/plans": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create Study Plan
         * @description Create and persist a deterministic study plan for owned documents.
         */
        post: operations["create_study_plan_study_plans_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/study/plans/current": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Current Study Plan
         * @description Get the most recently created plan for the authenticated user.
         */
        get: operations["get_current_study_plan_study_plans_current_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/study/plans/{plan_id}/days/{scheduled_date}/done": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Mark Study Day Done
         * @description Mark all activities on one owned plan date complete or incomplete.
         */
        patch: operations["mark_study_day_done_study_plans__plan_id__days__scheduled_date__done_patch"];
        trace?: never;
    };
    "/study/plans/{plan_id}/items/{item_id}/done": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Mark Study Activity Done
         * @description Mark one activity done only when both plan and item are owner-scoped.
         */
        patch: operations["mark_study_activity_done_study_plans__plan_id__items__item_id__done_patch"];
        trace?: never;
    };
    "/study/plans/{plan_id}/regenerate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Regenerate Study Plan
         * @description Rebuild future activities from today while keeping completed items.
         */
        post: operations["regenerate_study_plan_study_plans__plan_id__regenerate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/study/multi-document/qa": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Ask Across Documents
         * @description Answer one question from a bounded set of the user's documents.
         */
        post: operations["ask_across_documents_study_multi_document_qa_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/study/documents/compare": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Compare Owned Documents
         * @description Compare two owned documents using stored terms and section embeddings.
         */
        post: operations["compare_owned_documents_study_documents_compare_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/export/{kind}/{item_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Download Study Export
         * @description Generate an authenticated, owner-scoped study export in memory.
         */
        get: operations["download_study_export_export__kind___item_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/qa/extractive": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Extractive Qa
         * @description Retrieve only owned document chunks and predict the strongest answer span.
         */
        post: operations["extractive_qa_lab_qa_extractive_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/ner": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Named Entities
         * @description Return page-scoped NER entities with source offsets.
         */
        post: operations["named_entities_lab_ner_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/summarize/transformer": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Transformer Summary
         * @description Generate a bounded T5 summary with page citations for document inputs.
         */
        post: operations["transformer_summary_lab_summarize_transformer_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/question-generation": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Question Generation
         * @description Generate a T5 question from bounded text or an owned document chunk.
         */
        post: operations["question_generation_lab_question_generation_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/tokenizers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Tokenizer Comparison
         * @description Compare BPE, WordPiece, and SentencePiece on the exact supplied text.
         */
        get: operations["tokenizer_comparison_lab_tokenizers_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/attention": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Transformer Attention
         * @description Return DistilBERT self-attention as layer/head matrices.
         */
        get: operations["transformer_attention_lab_attention_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/positional-encoding": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Positional Encoding
         * @description Return the sinusoidal position-encoding matrix for a requested shape.
         */
        get: operations["positional_encoding_lab_positional_encoding_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/lab/transformers/results": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Transformer Results
         * @description Return locally persisted transformer evaluation tables.
         */
        get: operations["transformer_results_lab_transformers_results_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/documents/{document_id}/key-terms": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Document Key Terms
         * @description Combine Step 4 keyphrases with NER and persist glossary-ready terms.
         */
        post: operations["document_key_terms_documents__document_id__key_terms_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health
         * @description Report process health and key-free LLM provider readiness.
         */
        get: operations["health_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AnswerEntry */
        AnswerEntry: {
            /** Question Id */
            question_id: number;
            /** Answer */
            answer: string;
        };
        /** AnswerItem */
        AnswerItem: {
            /** Question Id */
            question_id: number;
            /**
             * Answer
             * @default
             */
            answer: string;
        };
        /** AnswerSet */
        AnswerSet: {
            /** Answers */
            answers?: components["schemas"]["AnswerEntry"][];
            /** Submission Token */
            submission_token: string;
        };
        /** Body_upload_document_documents_upload_post */
        Body_upload_document_documents_upload_post: {
            /** File */
            file: string;
        };
        /**
         * ClassifyRequest
         * @description Bounded text and a supported task/architecture for sequence inference.
         */
        ClassifyRequest: {
            /** Text */
            text: string;
            /**
             * Task
             * @enum {string}
             */
            task: "sentiment" | "difficulty";
            /**
             * Model
             * @enum {string}
             */
            model: "rnn" | "lstm" | "gru" | "bilstm";
        };
        /** CreateFromQuiz */
        CreateFromQuiz: {
            /** Quiz Id */
            quiz_id: number;
            metadata: components["schemas"]["TestMetadata"];
        };
        /** CreateSessionRequest */
        CreateSessionRequest: {
            /**
             * Title
             * @default New chat
             */
            title: string;
        };
        /**
         * Difficulty
         * @enum {string}
         */
        Difficulty: "easy" | "medium" | "hard";
        /**
         * DifficultyBatchRequest
         * @description An owner-scoped document ID whose chunks should be difficulty-tagged.
         */
        DifficultyBatchRequest: {
            /** Document Id */
            document_id: number;
        };
        /** DocumentComparisonRequest */
        DocumentComparisonRequest: {
            /** Document Ids */
            document_ids: number[];
        };
        /** DocumentPageResponse */
        DocumentPageResponse: {
            /** Document Id */
            document_id: number;
            /** Page Number */
            page_number: number;
            /** Text */
            text: string;
            /** Cleaned Text */
            cleaned_text: string | null;
            /** Headings */
            headings: {
                [key: string]: string | number | boolean;
            }[];
            /** Tables */
            tables: (string | null)[][][];
            /** Ocr Status */
            ocr_status: string;
        };
        /** DocumentResponse */
        DocumentResponse: {
            /** Id */
            id: number;
            /** Title */
            title: string;
            /** Status */
            status: string;
            /** Progress */
            progress: number;
            /** Error Message */
            error_message: string | null;
            /** Page Count */
            page_count: number | null;
            /** Language */
            language: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
        };
        /**
         * ExtractiveQARequest
         * @description Bounded retrieval-augmented extractive QA request.
         */
        ExtractiveQARequest: {
            /** Question */
            question: string;
            /** Doc Ids */
            doc_ids?: number[] | null;
            /**
             * Mode
             * @default hybrid
             * @enum {string}
             */
            mode: "tfidf" | "bm25" | "word2vec" | "dense" | "hybrid";
            /**
             * K
             * @default 5
             */
            k: number;
        };
        /** FeedbackRequest */
        FeedbackRequest: {
            /**
             * Feedback
             * @enum {string}
             */
            feedback: "thumbs_up" | "thumbs_down";
            /** Reason */
            reason?: string | null;
        };
        /**
         * GenerationSetting
         * @description One local decoding configuration; sampling settings are bounded.
         */
        GenerationSetting: {
            /**
             * Strategy
             * @enum {string}
             */
            strategy: "greedy" | "beam" | "top_k" | "top_p";
            /**
             * Max New Tokens
             * @default 24
             */
            max_new_tokens: number;
            /**
             * Num Beams
             * @default 3
             */
            num_beams: number;
            /**
             * Top K
             * @default 40
             */
            top_k: number;
            /**
             * Top P
             * @default 0.9
             */
            top_p: number;
            /**
             * Temperature
             * @default 1
             */
            temperature: number;
            /**
             * Repetition Penalty
             * @default 1
             */
            repetition_penalty: number;
        };
        /** GlossaryTermRequest */
        GlossaryTermRequest: {
            /** Term */
            term: string;
            /** Page */
            page?: number | null;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** LoginRequest */
        LoginRequest: {
            /** Email */
            email: string;
            /** Password */
            password: string;
        };
        /** LogoutRequest */
        LogoutRequest: {
            /** Refresh Token */
            refresh_token: string;
        };
        /** MetadataUpdate */
        MetadataUpdate: {
            /** Title */
            title?: string | null;
            /** Description */
            description?: string | null;
            /** Subject */
            subject?: string | null;
            /** Topic Labels */
            topic_labels?: string[] | null;
            /** Time Limit Seconds */
            time_limit_seconds?: number | null;
        };
        /** MultiDocumentQuestionRequest */
        MultiDocumentQuestionRequest: {
            /** Question */
            question: string;
            /** Document Ids */
            document_ids: number[];
            /**
             * Language
             * @default English
             * @enum {string}
             */
            language: "English" | "Hindi" | "Punjabi";
        };
        /**
         * PageRangeRequest
         * @description A document page interval for NER and summarization.
         */
        PageRangeRequest: {
            /** Text */
            text?: string | null;
            /** Document Id */
            document_id?: number | null;
            /** Page Start */
            page_start?: number | null;
            /** Page End */
            page_end?: number | null;
        };
        /**
         * PerplexityRequest
         * @description Bounded text for local causal language-model perplexity.
         */
        PerplexityRequest: {
            /** Text */
            text: string;
        };
        /** PostMessageRequest */
        PostMessageRequest: {
            /** Query */
            query: string;
            /**
             * Mode
             * @default normal
             * @enum {string}
             */
            mode: "normal" | "simple" | "in-depth" | "exam-style";
            /**
             * Language
             * @default English
             * @enum {string}
             */
            language: "English" | "Hindi" | "Punjabi";
            /** Doc Ids */
            doc_ids?: number[] | null;
        };
        /**
         * PreprocessRequest
         * @description Text or an owner-scoped document page range to preprocess.
         */
        PreprocessRequest: {
            /** Text */
            text?: string | null;
            /** Document Id */
            document_id?: number | null;
            /** Page Start */
            page_start?: number | null;
            /** Page End */
            page_end?: number | null;
            /** Steps */
            steps?: string[];
        };
        /** PublicProfileUpdate */
        PublicProfileUpdate: {
            /** Public Handle */
            public_handle?: string | null;
            /** Show On Leaderboards */
            show_on_leaderboards?: boolean | null;
        };
        /**
         * QuestionGenerationRequest
         * @description A source chunk or bounded text and an optional answer span.
         */
        QuestionGenerationRequest: {
            /** Chunk Id */
            chunk_id?: number | null;
            /** Text */
            text?: string | null;
            /** Answer */
            answer?: string | null;
        };
        /**
         * RechunkRequest
         * @description Optional chunk size and sentence-overlap settings.
         */
        RechunkRequest: {
            /**
             * Chunk Size
             * @default 400
             */
            chunk_size: number;
            /**
             * Overlap
             * @default 50
             */
            overlap: number;
        };
        /** RefreshRequest */
        RefreshRequest: {
            /** Refresh Token */
            refresh_token: string;
        };
        /** RegisterRequest */
        RegisterRequest: {
            /** Email */
            email: string;
            /** Full Name */
            full_name: string;
            /** Password */
            password: string;
        };
        /** ReportRequest */
        ReportRequest: {
            /** Reason */
            reason: string;
        };
        /**
         * ReviewRating
         * @enum {string}
         */
        ReviewRating: "Again" | "Hard" | "Good" | "Easy";
        /** ReviewRequest */
        ReviewRequest: {
            rating: components["schemas"]["ReviewRating"];
        };
        /**
         * SearchRequest
         * @description A bounded query over an optional set of owned documents.
         */
        SearchRequest: {
            /** Query */
            query: string;
            /**
             * Mode
             * @default tfidf
             * @enum {string}
             */
            mode: "tfidf" | "bm25" | "word2vec" | "dense" | "hybrid";
            /** Doc Ids */
            doc_ids?: number[] | null;
            /**
             * K
             * @default 5
             */
            k: number;
            /**
             * Rerank
             * @default false
             */
            rerank: boolean;
        };
        /**
         * Seq2SeqSummaryRequest
         * @description Bounded text or an owner-scoped document page range to summarize.
         */
        Seq2SeqSummaryRequest: {
            /** Text */
            text?: string | null;
            /** Document Id */
            document_id?: number | null;
            /** Page Start */
            page_start?: number | null;
            /** Page End */
            page_end?: number | null;
            /**
             * Model
             * @default bahdanau
             * @enum {string}
             */
            model: "none" | "bahdanau" | "luong";
            /**
             * Decoding
             * @default beam
             * @enum {string}
             */
            decoding: "greedy" | "beam";
            /**
             * Beam Width
             * @default 4
             */
            beam_width: number;
        };
        /** StatusUpdate */
        StatusUpdate: {
            /**
             * Status
             * @enum {string}
             */
            status: "approved" | "rejected" | "hidden";
        };
        /** StudentSubmission */
        StudentSubmission: {
            /** Quiz Id */
            quiz_id: number;
            metadata: components["schemas"]["TestMetadata"];
            /**
             * Rights Confirmed
             * @default false
             */
            rights_confirmed: boolean;
        };
        /** StudyPlanRequest */
        StudyPlanRequest: {
            /**
             * Exam Date
             * Format: date
             */
            exam_date: string;
            /** Daily Minutes */
            daily_minutes: number;
            /** Document Ids */
            document_ids: number[];
        };
        /** SubmitAnswers */
        SubmitAnswers: {
            /** Answers */
            answers: components["schemas"]["AnswerItem"][];
        };
        /** SummaryRequest */
        SummaryRequest: {
            /**
             * Summary Type
             * @default short
             * @enum {string}
             */
            summary_type: "short" | "detailed" | "chapter_wise";
            /**
             * Engine
             * @default extractive
             * @enum {string}
             */
            engine: "extractive" | "t5" | "llm";
            /** Page Start */
            page_start?: number | null;
            /** Page End */
            page_end?: number | null;
            /**
             * Regenerate
             * @default false
             */
            regenerate: boolean;
            /**
             * Run Async
             * @default false
             */
            run_async: boolean;
        };
        /** SuspendRequest */
        SuspendRequest: {
            /** Suspended */
            suspended: boolean;
        };
        /** TestMetadata */
        TestMetadata: {
            /** Title */
            title: string;
            /** Description */
            description?: string | null;
            /** Subject */
            subject: string;
            /** Topic Labels */
            topic_labels?: string[];
            /** Time Limit Seconds */
            time_limit_seconds: number;
        };
        /** TokenResponse */
        TokenResponse: {
            /** Access Token */
            access_token: string;
            /** Refresh Token */
            refresh_token: string;
            /**
             * Token Type
             * @default bearer
             */
            token_type: string;
            user: components["schemas"]["UserResponse"];
        };
        /**
         * TransformerSummaryRequest
         * @description A source and supported transformer decoding strategy.
         */
        TransformerSummaryRequest: {
            /** Text */
            text?: string | null;
            /** Document Id */
            document_id?: number | null;
            /** Page Start */
            page_start?: number | null;
            /** Page End */
            page_end?: number | null;
            /**
             * Decoding
             * @default greedy
             * @enum {string}
             */
            decoding: "greedy" | "beam";
        };
        /** UserResponse */
        UserResponse: {
            /** Id */
            id: number;
            /** Email */
            email: string;
            /** Full Name */
            full_name: string;
            /** Role */
            role: string;
            /** Public Handle */
            public_handle: string;
            /** Show On Leaderboards */
            show_on_leaderboards: boolean;
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
        /**
         * Word2VecTrainRequest
         * @description Bounded Word2Vec parameters for an owned document.
         */
        Word2VecTrainRequest: {
            /** Document Id */
            document_id: number;
            /**
             * Architecture
             * @enum {string}
             */
            architecture: "cbow" | "skipgram";
            /**
             * Vector Size
             * @default 100
             */
            vector_size: number;
            /**
             * Window
             * @default 5
             */
            window: number;
            /**
             * Min Count
             * @default 1
             */
            min_count: number;
            /**
             * Epochs
             * @default 20
             */
            epochs: number;
            /**
             * Negative
             * @default 5
             */
            negative: number;
            /**
             * Seed
             * @default 42
             */
            seed: number;
        };
        /**
         * GenerationRequest
         * @description Prompt with 1-6 side-by-side generation configurations.
         */
        app__routers__rag_playground__GenerationRequest: {
            /** Prompt */
            prompt: string;
            /** Settings */
            settings: components["schemas"]["GenerationSetting"][];
        };
        /**
         * GenerationRequest
         * @description Bounded quiz-generation request.
         */
        app__services__quiz__schemas__GenerationRequest: {
            /**
             * Title
             * @default Study quiz
             */
            title: string;
            /** Document Ids */
            document_ids: number[];
            /** Page Start */
            page_start?: number | null;
            /** Page End */
            page_end?: number | null;
            /** Topics */
            topics?: string[];
            /** Chunk Ids */
            chunk_ids?: number[];
            /**
             * Question Count
             * @default 10
             */
            question_count: number;
            /**
             * Engine
             * @default classic
             */
            engine: string;
            difficulty?: components["schemas"]["Difficulty"] | null;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    register_auth_register_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RegisterRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TokenResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_public_profile_auth_profile_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    update_public_profile_auth_profile_patch: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PublicProfileUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    login_auth_login_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LoginRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TokenResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    refresh_auth_refresh_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RefreshRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TokenResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    logout_auth_logout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LogoutRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_score_history_analytics_score_history_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    get_topic_accuracy_analytics_topic_accuracy_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    get_weak_topics_analytics_weak_topics_get: {
        parameters: {
            query?: {
                threshold_percent?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_study_time_analytics_study_time_get: {
        parameters: {
            query?: {
                days?: number;
                seconds_per_card?: number;
                seconds_per_chat_message?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_streaks_analytics_streaks_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    get_flashcard_retention_analytics_flashcard_retention_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    get_summary_analytics_summary_get: {
        parameters: {
            query?: {
                threshold_percent?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upload_document_documents_upload_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_upload_document_documents_upload_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DocumentResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_documents_documents_get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DocumentResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_document_status_documents__document_id__status_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DocumentResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    rechunk_document_documents__document_id__rechunk_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RechunkRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reindex_document_documents__document_id__reindex_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: number;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    stream_document_events_documents__document_id__events_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_document_page_documents__document_id__pages__page_number__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: number;
                page_number: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DocumentPageResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_document_page_image_documents__document_id__pages__page_number__image_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: number;
                page_number: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_document_documents__document_id__download_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_document_documents__document_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DocumentResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_document_documents__document_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    preprocess_lab_preprocess_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PreprocessRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    classify_text_lab_classify_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ClassifyRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    summarize_seq2seq_lab_summarize_seq2seq_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Seq2SeqSummaryRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    seq2seq_results_lab_seq2seq_results_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    classify_document_chunks_lab_difficulty_batch_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DifficultyBatchRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    document_ngrams_lab_ngrams_get: {
        parameters: {
            query: {
                document_id: number;
                n?: number | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    document_tfidf_terms_lab_tfidf_terms_get: {
        parameters: {
            query: {
                document_id: number;
                top_n?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    document_keyphrases_lab_keyphrases_get: {
        parameters: {
            query: {
                document_id: number;
                method?: string;
                top_n?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    train_document_word2vec_lab_word2vec_train_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Word2VecTrainRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    embeddings_similar_lab_embeddings_similar_get: {
        parameters: {
            query: {
                document_id: number;
                word: string;
                model?: "cbow" | "skipgram" | "glove";
                topn?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    embeddings_similarity_lab_embeddings_similarity_get: {
        parameters: {
            query: {
                w1: string;
                w2: string;
                model?: "cbow" | "skipgram" | "glove";
                document_id?: number | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    embeddings_analogy_lab_embeddings_analogy_get: {
        parameters: {
            query: {
                a: string;
                b: string;
                c: string;
                model?: "cbow" | "skipgram" | "glove";
                document_id?: number | null;
                topn?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    embeddings_compare_lab_embeddings_compare_get: {
        parameters: {
            query: {
                word: string;
                document_id: number;
                topn?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    embeddings_projection_lab_embeddings_projection_get: {
        parameters: {
            query: {
                document_id: number;
                model: "cbow" | "skipgram" | "glove";
                method?: string;
                dims?: number;
                top_n?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    generate_lab_generate_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["app__routers__rag_playground__GenerationRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    perplexity_lab_perplexity_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PerplexityRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    search_search_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SearchRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_sessions_chat_sessions_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    }[];
                };
            };
        };
    };
    create_session_chat_sessions_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateSessionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_session_chat_sessions__session_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_session_chat_sessions__session_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    post_message_chat_sessions__session_id__messages_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PostMessageRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    submit_feedback_chat_messages__message_id__feedback_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                message_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FeedbackRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_quizzes_quizzes_get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    }[];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_quiz_quizzes_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["app__services__quiz__schemas__GenerationRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_quiz_quizzes__quiz_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                quiz_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    question_explanation_quizzes__quiz_id__questions__question_id__explanation_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                quiz_id: number;
                question_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    start_attempt_quizzes__quiz_id__attempts_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                quiz_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: number;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    submit_answers_quizzes__quiz_id__attempts__attempt_id__submit_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                quiz_id: number;
                attempt_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SubmitAnswers"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    results_quizzes__quiz_id__results__attempt_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                quiz_id: number;
                attempt_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    retake_quizzes__quiz_id__retake_post: {
        parameters: {
            query: {
                attempt_id: number;
            };
            header?: never;
            path: {
                quiz_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    exam_quizzes__quiz_id__exam__format__get: {
        parameters: {
            query?: {
                marks_per_question?: number;
            };
            header?: never;
            path: {
                quiz_id: number;
                format: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_public_tests_public_tests_get: {
        parameters: {
            query?: {
                subject?: string | null;
                topic?: string | null;
                search?: string | null;
                sort?: "newest" | "popularity";
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    }[];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    global_accuracy_leaderboard_public_tests_leaderboards_accuracy_get: {
        parameters: {
            query?: {
                window?: "weekly" | "all-time";
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    my_public_test_overview_public_tests_me_overview_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    get_public_test_public_tests__test_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                test_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_public_test_statistics_public_tests__test_id__statistics_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                test_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_public_test_leaderboard_public_tests__test_id__leaderboard_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                test_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    admin_create_from_quiz_public_tests_admin_tests_from_quiz_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateFromQuiz"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    submit_quiz_for_publication_public_tests_submissions_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StudentSubmission"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_review_queue_public_tests_admin_queue_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    }[];
                };
            };
        };
    };
    edit_test_metadata_public_tests_admin_tests__test_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                test_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MetadataUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    moderate_test_public_tests_admin_tests__test_id__status_patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                test_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StatusUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    report_test_public_tests__test_id__reports_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                test_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReportRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    start_test_attempt_public_tests__test_id__attempts_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                test_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    save_test_answers_public_tests__test_id__attempts__attempt_id__answers_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                test_id: number;
                attempt_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AnswerSet"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: number;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    submit_test_answers_public_tests__test_id__attempts__attempt_id__submit_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                test_id: number;
                attempt_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AnswerSet"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    generate_flashcards_study_documents__document_id__flashcards_generate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_due_flashcards_study_flashcards_due_get: {
        parameters: {
            query?: {
                document_id?: number | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    }[];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upcoming_flashcard_counts_study_flashcards_upcoming_get: {
        parameters: {
            query?: {
                days?: number;
                document_id?: number | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    review_flashcard_study_flashcards__card_id__review_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                card_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReviewRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_flashcard_study_flashcards__card_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                card_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    set_flashcard_suspended_study_flashcards__card_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                card_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SuspendRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    flashcard_deck_stats_study_documents__document_id__flashcards_stats_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_glossary_terms_study_documents__document_id__glossary_get: {
        parameters: {
            query?: {
                search?: string | null;
                limit?: number;
                offset?: number;
            };
            header?: never;
            path: {
                document_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_custom_glossary_term_study_documents__document_id__glossary_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GlossaryTermRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    regenerate_document_glossary_study_documents__document_id__glossary_regenerate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    edit_custom_glossary_term_study_glossary__term_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                term_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GlossaryTermRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_document_summaries_study_documents__document_id__summaries_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    }[];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_summary_study_documents__document_id__summaries_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SummaryRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_summary_study_summaries__summary_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                summary_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_summary_study_summaries__summary_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                summary_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_summary_job_study_summaries_jobs__job_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_chapter_notes_study_documents__document_id__notes_get: {
        parameters: {
            query?: {
                page_start?: number | null;
                page_end?: number | null;
            };
            header?: never;
            path: {
                document_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_cheat_sheet_study_documents__document_id__cheat_sheet_get: {
        parameters: {
            query?: {
                page_start?: number | null;
                page_end?: number | null;
            };
            header?: never;
            path: {
                document_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_document_graph_study_documents__document_id__graph_get: {
        parameters: {
            query?: {
                chapter?: string | null;
                page_start?: number | null;
                page_end?: number | null;
                max_nodes?: number;
                label_relations?: boolean;
            };
            header?: never;
            path: {
                document_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_graph_node_study_documents__document_id__graph_nodes__node_id__get: {
        parameters: {
            query?: {
                chapter?: string | null;
                page_start?: number | null;
                page_end?: number | null;
            };
            header?: never;
            path: {
                document_id: number;
                node_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_study_plan_study_plans_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StudyPlanRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_current_study_plan_study_plans_current_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    mark_study_day_done_study_plans__plan_id__days__scheduled_date__done_patch: {
        parameters: {
            query: {
                done: boolean;
            };
            header?: never;
            path: {
                plan_id: number;
                scheduled_date: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    mark_study_activity_done_study_plans__plan_id__items__item_id__done_patch: {
        parameters: {
            query: {
                done: boolean;
            };
            header?: never;
            path: {
                plan_id: number;
                item_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    regenerate_study_plan_study_plans__plan_id__regenerate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    ask_across_documents_study_multi_document_qa_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MultiDocumentQuestionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    compare_owned_documents_study_documents_compare_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DocumentComparisonRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_study_export_export__kind___item_id__get: {
        parameters: {
            query: {
                format: string;
                page_start?: number | null;
                page_end?: number | null;
                include_answers?: boolean;
            };
            header?: never;
            path: {
                kind: string;
                item_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    extractive_qa_lab_qa_extractive_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ExtractiveQARequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    named_entities_lab_ner_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PageRangeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    transformer_summary_lab_summarize_transformer_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TransformerSummaryRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    question_generation_lab_question_generation_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QuestionGenerationRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    tokenizer_comparison_lab_tokenizers_get: {
        parameters: {
            query: {
                text: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    transformer_attention_lab_attention_get: {
        parameters: {
            query: {
                sentence: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    positional_encoding_lab_positional_encoding_get: {
        parameters: {
            query?: {
                length?: number;
                dimension?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    transformer_results_lab_transformers_results_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    document_key_terms_documents__document_id__key_terms_post: {
        parameters: {
            query?: {
                method?: string;
                top_n?: number;
            };
            header?: never;
            path: {
                document_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    health_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
}
