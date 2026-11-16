"""End-to-end RAG chat pipeline with follow-up rewriting,
hybrid retrieval, grounding, and streaming.
"""

import json
import logging
import re
import time
from collections.abc import Iterator, Sequence
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import Chunk, Document, DocumentKeyTerm, Message, User
from app.retrieval import ChunkRecord, get_retriever
from app.services.rag.grounding import evaluate_grounding
from app.services.rag.prompts import (
    REWRITE_SYSTEM_PROMPT,
    build_context_block,
    build_grounded_context,
    build_grounded_system_prompt,
    build_system_prompt,
    rule_based_rewrite,
)
from app.services.rag.providers import (
    ExtractiveProvider,
    GeminiProvider,
    GroqProvider,
    LLMProvider,
    OllamaProvider,
    ProviderChain,
    ProviderError,
    ProviderUnavailableError,
    RateLimitError,
)
from app.services.rag.safety import AnswerCache, RateLimiter, redact_secrets
from app.services.rag.tracing import trace_chat
from app.services.reranker import get_cross_encoder_reranker

logger = logging.getLogger(__name__)

# Process-wide in-memory rate limiter and answer cache instances
_rate_limiter = RateLimiter()
_answer_cache = AnswerCache()


def get_global_rate_limiter() -> RateLimiter:
    return _rate_limiter


def get_global_answer_cache() -> AnswerCache:
    return _answer_cache


class RAGChatPipeline:
    """End-to-end RAG orchestrator with privacy guards and multi-provider fallbacks."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        extractive_provider: ExtractiveProvider | None = None,
        rate_limiter: RateLimiter | None = None,
        cache: AnswerCache | None = None,
        context_retriever: Any = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.rate_limiter = rate_limiter or _rate_limiter
        self.cache = cache or _answer_cache
        self.context_retriever = context_retriever
        self.extractive_provider = extractive_provider or ExtractiveProvider(
            confidence_threshold=self.settings.transformer_no_answer_threshold
        )
        self.provider = provider or self._resolve_primary_provider()

    def _resolve_primary_provider(self) -> LLMProvider:
        if (
            "," in self.settings.llm_provider_chain
            or self.settings.llm_provider_chain.strip().lower() != "gemini"
        ):
            providers: list[Any] = []
            for name in self.settings.llm_provider_chain.split(","):
                name = name.strip().lower()
                if name == "gemini":
                    providers.append(
                        GeminiProvider(
                            api_key=self.settings.gemini_api_key,
                            model_name=self.settings.llm_model,
                            timeout_seconds=self.settings.rag_request_timeout_seconds,
                        )
                    )
                elif name == "groq":
                    providers.append(
                        GroqProvider(
                            timeout_seconds=self.settings.rag_request_timeout_seconds
                        )
                    )
                elif name == "ollama":
                    providers.append(
                        OllamaProvider(
                            base_url=self.settings.ollama_base_url,
                            model_name=self.settings.ollama_model,
                            timeout_seconds=self.settings.rag_request_timeout_seconds,
                        )
                    )
                elif name == "extractive":
                    continue
            if providers:
                return ProviderChain(
                    providers, context_budget=self.settings.llm_context_token_budget
                )
            if "extractive" in self.settings.llm_provider_chain.lower():
                return self.extractive_provider
        provider_name = (self.settings.llm_provider or "gemini").lower()
        if provider_name == "gemini":
            return GeminiProvider(
                api_key=self.settings.gemini_api_key,
                model_name=self.settings.llm_model,
                timeout_seconds=self.settings.rag_request_timeout_seconds,
            )
        if provider_name == "ollama":
            return OllamaProvider(
                base_url=self.settings.ollama_base_url,
                model_name=self.settings.ollama_model,
                timeout_seconds=self.settings.rag_request_timeout_seconds,
            )
        if provider_name == "extractive":
            return self.extractive_provider
        return GeminiProvider(
            api_key=self.settings.gemini_api_key,
            model_name=self.settings.llm_model,
        )

    def rewrite_query(
        self,
        query: str,
        history: list[dict[str, str]],
        provider: LLMProvider | None = None,
    ) -> str:
        """Rewrite follow-up question using chat history."""
        if not history:
            return query.strip()

        active_provider = provider or self.provider
        # If active provider is an external or local LLM (not extractive), try rewriting
        if getattr(active_provider, "name", "") in {"gemini", "groq", "ollama", "fake"}:
            try:
                history_text = "\n".join(
                    f"{msg.get('role', 'user')}: {msg.get('content', '')}"
                    for msg in history[-4:]
                )
                prompt = (
                    f"Chat History:\n{history_text}\n\n"
                    f"Follow-up Question: {query}\n\n"
                    "Rewritten Search Query:"
                )
                rewritten = active_provider.generate(prompt, REWRITE_SYSTEM_PROMPT)
                clean_rewrite = rewritten.strip().strip('"').strip("'")
                if clean_rewrite:
                    return clean_rewrite
            except Exception as exc:
                logger.debug(
                    "LLM query rewrite failed; falling back to rule-based: %s", exc
                )

        return rule_based_rewrite(query, history)

    def retrieve_context(
        self,
        db: Session,
        user_id: int,
        query: str,
        doc_ids: Sequence[int] | None = None,
        top_k: int = 5,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Retrieve top chunks via Hybrid retrieval and Cross-Encoder reranking."""
        if self.context_retriever is not None:
            return self.context_retriever(db, user_id, query, doc_ids, top_k)

        doc_query = select(Document).where(Document.owner_id == user_id)
        if doc_ids:
            doc_query = doc_query.where(Document.id.in_(doc_ids))
        owned_docs = {d.id: d for d in db.scalars(doc_query)}

        if not owned_docs:
            return [], False

        chunks = list(
            db.scalars(
                select(Chunk)
                .where(Chunk.doc_id.in_(owned_docs.keys()))
                .order_by(Chunk.doc_id, Chunk.chunk_index)
            )
        )
        if not chunks:
            return [], False

        records = [
            ChunkRecord(
                chunk_id=c.id,
                document_id=c.doc_id,
                text=c.text,
                page_start=c.page_start,
                page_end=c.page_end,
                section=c.section,
                vector_id=c.vector_id,
            )
            for c in chunks
        ]

        retriever = get_retriever("hybrid", user_id, records)
        initial_results = retriever.retrieve(
            query, list(owned_docs.keys()), k=max(top_k * 3, 10)
        )

        reranked_results = initial_results
        try:
            reranker = get_cross_encoder_reranker()
            outcome = reranker.rerank(query, initial_results, top_k)
            if outcome.results:
                reranked_results = outcome.results
        except Exception as exc:
            logger.debug("Reranking failed or unavailable; using hybrid order: %s", exc)
            reranked_results = initial_results[:top_k]

        context_chunks: list[dict[str, Any]] = []
        any_private = False

        for res in reranked_results[:top_k]:
            doc = owned_docs.get(res.document_id)
            is_private = getattr(doc, "is_private", False)
            if is_private:
                any_private = True
            context_chunks.append(
                {
                    "chunk_id": res.chunk_id,
                    "document_id": res.document_id,
                    "document_title": (
                        doc.title if doc else f"document_{res.document_id}"
                    ),
                    "page": res.page,
                    "text": res.text,
                    "is_private": is_private,
                    "retrieval_score": (
                        res.original_score
                        if res.original_score is not None
                        else res.score
                    ),
                    "rerank_score": res.rerank_score,
                    "score_components": res.components or {},
                }
            )

        return context_chunks, any_private

    def retrieval_confidence(self, chunks: list[dict[str, Any]]) -> float:
        """Use the top reranker score, or retrieval score when reranking is absent."""
        if not chunks:
            return 0.0
        top = chunks[0]
        score = top.get("rerank_score")
        if score is None:
            score = top.get("retrieval_score", top.get("score", 0.0))
        try:
            return float(score)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def build_explanation(
        chunks: list[dict[str, Any]],
        answer: str,
        mode: str,
        provider: str,
        latency_ms: float,
    ) -> dict[str, Any]:
        """Return evidence, usage highlights, provider, mode, and timing metadata."""
        return {
            "chunks": chunks,
            "answer_sentences": [item for item in answer.splitlines() if item.strip()],
            "provider": provider,
            "mode": mode,
            "latency_ms": round(latency_ms, 2),
        }

    @staticmethod
    def nearest_document_topics(
        db: Session, user_id: int, doc_ids: list[int] | None, query: str
    ) -> list[dict[str, Any]]:
        """Find nearby section names and key terms only within the user's documents."""
        section_query = (
            select(Chunk.section, Chunk.page, Document.title)
            .join(Document, Document.id == Chunk.doc_id)
            .where(Document.owner_id == user_id, Chunk.section.is_not(None))
        )
        term_query = (
            select(DocumentKeyTerm.term, DocumentKeyTerm.page, Document.title)
            .join(Document, Document.id == DocumentKeyTerm.document_id)
            .where(Document.owner_id == user_id)
        )
        if doc_ids is not None:
            section_query = section_query.where(Document.id.in_(doc_ids))
            term_query = term_query.where(Document.id.in_(doc_ids))
        candidates = list(db.execute(section_query)) + list(db.execute(term_query))
        query_words = set(re.findall(r"[a-z0-9]+", query.casefold()))
        ranked: dict[str, tuple[float, dict[str, Any]]] = {}
        for label, page, title in candidates:
            label = str(label or "").strip()
            words = set(re.findall(r"[a-z0-9]+", label.casefold()))
            if len(label) < 3 or not words:
                continue
            overlap = len(words & query_words) / len(words)
            similarity = SequenceMatcher(
                None, " ".join(sorted(words)), " ".join(sorted(query_words))
            ).ratio()
            score = overlap + similarity * 0.25
            key = label.casefold()
            if key not in ranked or score > ranked[key][0]:
                ranked[key] = (
                    score,
                    {"topic": label, "page": page, "document_title": title},
                )
        ordered = sorted(ranked.values(), key=lambda row: row[0], reverse=True)
        return [item for _, item in ordered[:3]]

    def parse_citations(
        self, answer_text: str, chunks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Extract citations matching [document, p.N] from generated answer."""
        citation_pattern = re.compile(r"\[([^\]]+),\s*p\.?(\d+)\]", re.IGNORECASE)
        found_matches = citation_pattern.findall(answer_text)

        citations: list[dict[str, Any]] = []
        seen = set()

        for doc_title, page_str in found_matches:
            title_clean = doc_title.strip()
            page_int = int(page_str)
            key = (title_clean.lower(), page_int)
            if key not in seen:
                seen.add(key)
                matched_chunk_id = None
                for c in chunks:
                    if (
                        c["document_title"].lower() == title_clean.lower()
                        and c["page"] == page_int
                    ):
                        matched_chunk_id = c["chunk_id"]
                        break
                citations.append(
                    {
                        "document_title": title_clean,
                        "page": page_int,
                        "chunk_id": matched_chunk_id,
                    }
                )

        return citations

    def stream_chat(
        self,
        db: Session,
        user_id: int,
        session_id: int,
        query: str,
        mode: str = "normal",
        language: str = "English",
        doc_ids: list[int] | None = None,
        use_web_search: bool = False,
    ) -> Iterator[str]:
        """Execute chat pipeline and stream Server-Sent Events (SSE)."""
        start_time = time.perf_counter()

        # 1. Fetch recent chat history
        recent_messages = list(
            db.scalars(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at.asc())
            )
        )
        history = [{"role": m.role, "content": m.content} for m in recent_messages]

        # 2. Rewrite follow-up query
        search_query = self.rewrite_query(query, history)

        # 3. Hybrid retrieval + rerank
        chunks, has_private_doc = self.retrieve_context(
            db, user_id, search_query, doc_ids
        )
        web_results: list[dict[str, str]] = []
        web_notice = None
        privacy_query = select(Document.is_private).where(Document.owner_id == user_id)
        if doc_ids:
            privacy_query = privacy_query.where(Document.id.in_(doc_ids))
        scope_has_private = any(db.scalars(privacy_query))
        requester = db.get(User, user_id)
        local_only = bool(requester and requester.local_models_only)
        if (
            use_web_search
            and not has_private_doc
            and not scope_has_private
            and not local_only
        ):
            from app.services.web_search import search_web

            web_results, web_notice = search_web(search_query, self.settings)
        elif use_web_search and local_only:
            web_notice = (
                "Web search is unavailable in local-only mode; "
                "continuing with your notes only."
            )
        elif use_web_search and (has_private_doc or scope_has_private):
            web_notice = (
                "Web search is unavailable for private documents; "
                "continuing with your notes only."
            )
        chunk_ids = [c["chunk_id"] for c in chunks]
        top_score = self.retrieval_confidence(chunks)

        if (
            not chunks or top_score < self.settings.rag_retrieval_confidence_threshold
        ) and not web_results:
            refusal = "not found in the document"
            nearest_topics = self.nearest_document_topics(
                db, user_id, doc_ids, search_query
            )
            if nearest_topics:
                suggestions = "; ".join(
                    f"{item['topic']} [{item['document_title']}, p.{item['page']}]"
                    for item in nearest_topics
                )
                refusal += f". Try asking about: {suggestions}."
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            explanation = self.build_explanation(
                chunks, refusal, mode, "answered by: retrieval guard", latency_ms
            )
            if web_notice:
                explanation["web_notice"] = web_notice
            bot_msg = Message(
                session_id=session_id,
                role="assistant",
                content=refusal,
                citations=[],
                grounding_score=0.0,
                unsupported_sentences=[],
                explanation=explanation,
                provider="answered by: retrieval guard",
                latency_ms=round(latency_ms, 2),
            )
            db.add(bot_msg)
            db.commit()
            db.refresh(bot_msg)
            yield f"data: {json.dumps({'token': refusal})}\n\n"
            refusal_payload = {
                "done": True,
                "provider": bot_msg.provider,
                "citations": [],
                "grounding_score": 0.0,
                "unsupported_sentences": [],
                "explanation": explanation,
                "message_id": bot_msg.id,
                "latency_ms": round(latency_ms, 2),
                "pipeline_stages": {
                    "retrieval": "local hybrid retrieval; no relevant passage found",
                    "generation": "retrieval guard",
                    "validation": "local retrieval confidence threshold",
                },
            }
            yield f"data: {json.dumps(refusal_payload)}\n\n"
            return

        # 4. Check Answer Cache
        cached_hit = None if use_web_search else self.cache.get(query, chunk_ids, mode)
        if cached_hit:
            cached_answer = cached_hit["answer"]
            cached_citations = cached_hit["citations"]
            cached_provider = f"{cached_hit['provider']} (cache hit)"
            latency_ms = (time.perf_counter() - start_time) * 1000.0

            # Yield cached content
            yield f"data: {json.dumps({'token': cached_answer})}\n\n"

            # Persist assistant message
            grounding = evaluate_grounding(cached_answer, chunks, self.settings)
            explanation = self.build_explanation(
                grounding["chunks"], cached_answer, mode, cached_provider, latency_ms
            )
            bot_msg = Message(
                session_id=session_id,
                role="assistant",
                content=cached_answer,
                citations=cached_citations,
                grounding_score=grounding["grounding_score"],
                unsupported_sentences=grounding["unsupported_sentences"],
                explanation=explanation,
                provider=cached_provider,
                latency_ms=round(latency_ms, 2),
            )
            db.add(bot_msg)
            db.commit()
            db.refresh(bot_msg)

            cached_payload = {
                "done": True,
                "provider": cached_provider,
                "citations": cached_citations,
                "grounding_score": bot_msg.grounding_score,
                "unsupported_sentences": bot_msg.unsupported_sentences,
                "explanation": bot_msg.explanation,
                "message_id": bot_msg.id,
                "latency_ms": round(latency_ms, 2),
            }
            yield f"data: {json.dumps(cached_payload)}\n\n"
            return

        # 5. Free-tier Safety: In-memory rate limiting and request budget
        allowed, rate_reason = self.rate_limiter.check_and_consume(user_id)

        # 6. Provider Selection and Fallback Determination
        active_provider: LLMProvider = self.provider
        provider_label = f"answered by: {active_provider.name}"
        fallback_reason: str | None = None

        if not allowed:
            fallback_reason = "rate limit"
        elif has_private_doc:
            fallback_reason = "private document"
        elif not self.settings.allow_external_llm and getattr(
            active_provider, "is_external", False
        ):
            fallback_reason = "external llm disabled"
        elif (
            getattr(active_provider, "name", "") == "gemini"
            and not self.settings.gemini_api_key
        ):
            fallback_reason = "missing key"

        if fallback_reason:
            active_provider = self.extractive_provider
            provider_label = f"answered by: extractive (fallback: {fallback_reason})"

        # 7. Execution (with runtime fallback on error or 429)
        system_prompt = (
            build_grounded_system_prompt(mode, language)
            if web_results
            else build_system_prompt(mode, language)
        )
        context_block = (
            build_grounded_context(chunks, web_results)
            if web_results
            else build_context_block(chunks)
        )
        full_prompt = f"{context_block}\n\nUser Question: {query}\n\nAnswer:"

        answer_tokens: list[str] = []
        citations: list[dict[str, Any]] = []

        try:
            if isinstance(active_provider, ExtractiveProvider):
                extractive_ans, citations = active_provider.answer_with_chunks(
                    query, chunks
                )
                for token in active_provider.stream(extractive_ans):
                    safe_token = redact_secrets(
                        token,
                        [self.settings.gemini_api_key, self.settings.groq_api_key],
                    )
                    answer_tokens.append(safe_token)
                    yield f"data: {json.dumps({'token': safe_token})}\n\n"
            else:
                for token in active_provider.stream(full_prompt, system_prompt):
                    safe_token = redact_secrets(
                        token,
                        [self.settings.gemini_api_key, self.settings.groq_api_key],
                    )
                    answer_tokens.append(safe_token)
                    yield f"data: {json.dumps({'token': safe_token})}\n\n"

        except (
            RateLimitError,
            ProviderUnavailableError,
            ProviderError,
            Exception,
        ) as exc:
            err_reason = "rate limit" if isinstance(exc, RateLimitError) else "error"
            logger.warning(
                "Active provider failed; falling back to extractive: %s", exc
            )
            active_provider = self.extractive_provider
            if isinstance(self.provider, ProviderChain) and self.provider.skipped:
                skipped = ", ".join(
                    f"{item['provider']}:{item['reason']}"
                    for item in self.provider.skipped
                )
                provider_label = f"answered by: extractive (skipped: {skipped})"
            else:
                provider_label = f"answered by: extractive (fallback: {err_reason})"
            answer_tokens.clear()

            extractive_ans, citations = active_provider.answer_with_chunks(
                query, chunks
            )
            for token in active_provider.stream(extractive_ans):
                safe_token = redact_secrets(
                    token, [self.settings.gemini_api_key, self.settings.groq_api_key]
                )
                answer_tokens.append(safe_token)
                yield f"data: {json.dumps({'token': safe_token})}\n\n"

        final_answer = "".join(answer_tokens).strip()

        if isinstance(active_provider, ProviderChain):
            skipped = ", ".join(
                f"{item['provider']}:{item['reason']}"
                for item in active_provider.skipped
            )
            provider_label = f"answered by: {active_provider.last_provider}" + (
                f" (skipped: {skipped})" if skipped else ""
            )

        # Parse citations if not already provided by extractive provider
        if not citations:
            citations = self.parse_citations(final_answer, chunks)

        grounding = evaluate_grounding(final_answer, chunks, self.settings)
        total_latency_ms = (time.perf_counter() - start_time) * 1000.0
        evidence_by_id = {chunk.get("chunk_id"): chunk for chunk in grounding["chunks"]}
        for citation in citations:
            evidence = evidence_by_id.get(citation.get("chunk_id"), {})
            citation["highlight_offsets"] = evidence.get("highlight_offsets", [])
        explanation = self.build_explanation(
            grounding["chunks"], final_answer, mode, provider_label, total_latency_ms
        )
        explanation["sources"] = {
            "your_notes": [
                {
                    "document_title": c.get("document_title"),
                    "page": c.get("page"),
                    "chunk_id": c.get("chunk_id"),
                }
                for c in chunks
            ],
            "web": [
                {
                    "title": w["title"],
                    "url": w["url"],
                    "domain": w["domain"],
                    "snippet": w["snippet"],
                }
                for w in web_results
            ],
        }
        if web_notice:
            explanation["web_notice"] = web_notice
        token_count = getattr(
            active_provider, "last_token_count", len(final_answer.split())
        )

        # Safe logging: never log API key or full document text
        logger.info(
            "RAG completed | provider='%s' | tokens=%d | latency=%.2fms",
            provider_label,
            token_count,
            total_latency_ms,
        )

        # 8. Cache response if generated successfully
        if final_answer and not fallback_reason and not use_web_search:
            self.cache.set(
                query,
                chunk_ids,
                mode,
                final_answer,
                citations,
                provider_label,
                grounding_score=grounding["grounding_score"],
                unsupported_sentences=grounding["unsupported_sentences"],
            )

        # 9. Persist assistant message in DB
        safe_answer = redact_secrets(
            final_answer, [self.settings.gemini_api_key, self.settings.groq_api_key]
        )
        bot_msg = Message(
            session_id=session_id,
            role="assistant",
            content=safe_answer,
            citations=citations,
            grounding_score=grounding["grounding_score"],
            unsupported_sentences=grounding["unsupported_sentences"],
            explanation=explanation,
            provider=provider_label,
            latency_ms=round(total_latency_ms, 2),
        )
        db.add(bot_msg)
        db.commit()
        db.refresh(bot_msg)

        generation_provider = getattr(active_provider, "last_provider", "") or getattr(
            active_provider, "name", "local"
        )
        generation_model = getattr(active_provider, "last_model", "") or getattr(
            active_provider, "model_name", ""
        )
        final_payload = {
            "done": True,
            "provider": provider_label,
            "citations": citations,
            "grounding_score": bot_msg.grounding_score,
            "unsupported_sentences": bot_msg.unsupported_sentences,
            "explanation": explanation,
            "message_id": bot_msg.id,
            "latency_ms": round(total_latency_ms, 2),
            "pipeline_stages": {
                "retrieval": "local hybrid + reranker",
                "generation": f"{generation_provider}/{generation_model}".rstrip("/"),
                "validation": "local QA + grounding",
                **({"web": web_notice} if web_notice else {}),
            },
        }
        yield f"data: {json.dumps(final_payload)}\n\n"
        if not has_private_doc:
            trace_chat(
                question=query,
                answer=safe_answer,
                provider=provider_label,
                mode=mode,
                grounding_score=grounding["grounding_score"],
                settings=self.settings,
            )
