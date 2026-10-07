"""Replaceable query rewrite and multi-query expansion interfaces."""

from typing import Protocol


class QueryRewriter(Protocol):
    """Convert a user query to a retrieval-oriented query."""

    def rewrite(self, query: str) -> str:
        """Return a query suitable for retrieval."""


class QueryExpander(Protocol):
    """Produce retrieval variants from a query."""

    def expand(self, query: str) -> list[str]:
        """Return one or more query variants."""


class NoOpQueryRewriter:
    """Preserve the user's query until an LLM-backed rewriter is introduced."""

    def rewrite(self, query: str) -> str:
        return query


class NoOpQueryExpander:
    """Use one query until an LLM-backed expansion strategy is introduced."""

    def expand(self, query: str) -> list[str]:
        return [query]
