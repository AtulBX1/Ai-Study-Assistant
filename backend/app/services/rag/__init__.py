"""RAG service core providing multi-provider chat,
rate limiting, and fallbacks.
"""

from app.services.rag.grounding import evaluate_grounding, split_sentences
from app.services.rag.pipeline import (
    RAGChatPipeline,
    get_global_answer_cache,
    get_global_rate_limiter,
)
from app.services.rag.prompts import (
    MODE_INSTRUCTIONS,
    build_context_block,
    build_system_prompt,
    rule_based_rewrite,
)
from app.services.rag.providers import (
    ExtractiveProvider,
    FakeProvider,
    GeminiProvider,
    LLMProvider,
    OllamaProvider,
)
from app.services.rag.safety import AnswerCache, RateLimiter, normalize_question

__all__ = [
    "RAGChatPipeline",
    "get_global_rate_limiter",
    "get_global_answer_cache",
    "LLMProvider",
    "GeminiProvider",
    "OllamaProvider",
    "ExtractiveProvider",
    "FakeProvider",
    "RateLimiter",
    "AnswerCache",
    "normalize_question",
    "build_system_prompt",
    "build_context_block",
    "rule_based_rewrite",
    "MODE_INSTRUCTIONS",
    "evaluate_grounding",
    "split_sentences",
]
