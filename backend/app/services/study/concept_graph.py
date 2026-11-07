"""Evidence-grounded concept graphs from stored document terms and pages."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from copy import deepcopy
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, DocumentKeyTerm, DocumentPage, GlossaryTerm
from app.services.study.glossary import (
    find_evidence_sentence,
    normalize_term,
    split_sentences,
)

GRAPH_VERSION = "concept-graph-v1"
MAX_GRAPH_TEXT_BYTES = 1_000_000
_GRAPH_CACHE: dict[tuple[int, str, str], dict[str, Any]] = {}
_ENTITY_LABELS = {
    "person",
    "org",
    "organization",
    "gpe",
    "location",
    "product",
    "event",
    "work_of_art",
    "law",
    "language",
    "date",
    "time",
    "money",
    "percent",
    "facility",
}
_RELATION_PATTERNS = (
    ("is_a", r"\s+is\s+(?:a\s+)?(?:type|kind)\s+of\s+"),
    ("uses", r"\s+(?:uses|relies\s+on)\s+"),
    ("part_of", r"\s+(?:consists\s+of|contains|includes)\s+"),
    ("used_for", r"\s+(?:is\s+used\s+for|helps\s+with)\s+"),
)


def _term_pattern(label: str) -> re.Pattern[str]:
    words = re.escape(" ".join(label.split())).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<!\w){words}(?!\w)", re.IGNORECASE)


def _node_id(term_key: str) -> str:
    return f"node_{sha256(term_key.encode()).hexdigest()[:16]}"


def _relation_between(left: str, right: str, sentence: str) -> tuple[str, str] | None:
    for relation, separator in _RELATION_PATTERNS:
        for source, target in ((left, right), (right, left)):
            pattern = re.compile(
                rf"{_term_pattern(source).pattern}{separator}"
                rf"{_term_pattern(target).pattern}",
                re.IGNORECASE,
            )
            if pattern.search(sentence):
                return relation, source
    return None


def _term_type(source: str, label: str, glossary: bool = False) -> str:
    if glossary:
        return "glossary_term"
    if source.casefold() == "ner" or label.casefold() in _ENTITY_LABELS:
        return "entity"
    return "key_term"


def _build_nodes(
    *,
    pages: list[DocumentPage],
    key_terms: list[DocumentKeyTerm],
    glossary_terms: list[GlossaryTerm],
    max_nodes: int,
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for term in key_terms:
        label = " ".join(term.term.split())
        key = normalize_term(label)
        if not key:
            continue
        candidate = candidates.setdefault(
            key,
            {
                "id": _node_id(key),
                "label": label,
                "type": _term_type(term.source, term.label),
                "importance": 0.0,
                "pages": set(),
                "definition": None,
            },
        )
        candidate["importance"] += 1.0
        candidate["pages"].add(term.page)

    for term in glossary_terms:
        label = " ".join(term.term.split())
        key = normalize_term(label)
        if not key:
            continue
        candidate = candidates.setdefault(
            key,
            {
                "id": _node_id(key),
                "label": label,
                "type": "glossary_term",
                "importance": 0.0,
                "pages": set(),
                "definition": None,
            },
        )
        candidate["type"] = "glossary_term"
        candidate["importance"] = max(candidate["importance"], term.importance)
        candidate["pages"].add(term.page)
        candidate["definition"] = term.definition

    text_by_page = {page.page_number: page.text for page in pages}
    for candidate in candidates.values():
        matcher = _term_pattern(candidate["label"])
        matching_pages = {
            page_number: text
            for page_number, text in text_by_page.items()
            if matcher.search(text)
        }
        candidate["pages"].update(matching_pages)
        candidate["pages"] = sorted(set(candidate["pages"]) & set(text_by_page))
        if candidate["definition"] is None:
            candidate["definition"] = next(
                (
                    definition
                    for text in matching_pages.values()
                    if (definition := find_evidence_sentence(text, candidate["label"]))
                ),
                None,
            )
        candidate["importance"] = round(float(candidate["importance"]), 4)

    ranked = sorted(
        candidates.values(),
        key=lambda item: (-item["importance"], item["label"].casefold()),
    )[:max_nodes]
    return ranked


def _make_edges(
    nodes: list[dict[str, Any]], pages: list[DocumentPage]
) -> tuple[list[dict[str, Any]], set[str]]:
    node_matches = [(node, _term_pattern(node["label"])) for node in nodes]
    evidence: dict[tuple[str, str, str], list[tuple[str, int]]] = defaultdict(list)

    for page in pages:
        for sentence in split_sentences(page.text):
            present = [
                node for node, matcher in node_matches if matcher.search(sentence)
            ]
            for index, first in enumerate(present):
                for second in present[index + 1 :]:
                    source, target = sorted((first["id"], second["id"]))
                    relation = _relation_between(
                        first["label"], second["label"], sentence
                    )
                    if relation is None:
                        relation = "related_to"
                    else:
                        relation_name, relation_source = relation
                        relation = relation_name
                        if relation_source.casefold() == first["label"].casefold():
                            source, target = first["id"], second["id"]
                        else:
                            source, target = second["id"], first["id"]
                    evidence[(source, target, relation)].append(
                        (sentence.strip(), page.page_number)
                    )

    # Keep explicit pattern edges in preference to generic co-occurrence edges
    # for the same pair; all retained evidence remains verbatim from the source.
    patterned_pairs = {
        (source, target)
        for source, target, relation in evidence
        if relation != "related_to"
    }
    edges: list[dict[str, Any]] = []
    connected: set[str] = set()
    labels = {node["id"]: node["label"] for node in nodes}
    for (source, target, relation), items in sorted(evidence.items()):
        if relation == "related_to" and (source, target) in patterned_pairs:
            continue
        sentence, page = items[0]
        if not (
            _term_pattern(labels[source]).search(sentence)
            and _term_pattern(labels[target]).search(sentence)
        ):
            continue
        edges.append(
            {
                "source": source,
                "target": target,
                "relation": relation,
                "evidence_sentence": sentence,
                "page": page,
                "weight": len(items),
            }
        )
        connected.update((source, target))
    return edges, connected


def _label_relations(
    edges: list[dict[str, Any]], provider: Any
) -> list[dict[str, Any]]:
    if not edges:
        return edges
    prompt = (
        'Return JSON only: {"relations":[{"source":string,"target":string,'
        '"relation":"is_a|uses|part_of|used_for|related_to"}]}. '
        "Only relabel listed edges; do not add edges. Keep each evidence sentence "
        "unchanged.\n" + json.dumps(edges, ensure_ascii=True)
    )
    result = json.loads(provider.generate(prompt))
    relation_by_pair = {
        (edge["source"], edge["target"]): edge["relation"]
        for edge in result.get("relations", [])
        if edge.get("relation") in {"is_a", "uses", "part_of", "used_for", "related_to"}
    }
    labeled = deepcopy(edges)
    for edge in labeled:
        edge["relation"] = relation_by_pair.get(
            (edge["source"], edge["target"]), edge["relation"]
        )
    return labeled


def build_concept_graph(
    db: Session,
    *,
    document: Document,
    owner_id: int,
    page_start: int | None = None,
    page_end: int | None = None,
    max_nodes: int = 40,
    relation_provider: Any | None = None,
) -> dict[str, Any]:
    """Build and cache a small evidence-backed graph for an owned document."""
    query = select(DocumentPage).where(DocumentPage.document_id == document.id)
    if page_start is not None:
        query = query.where(DocumentPage.page_number >= page_start)
    if page_end is not None:
        query = query.where(DocumentPage.page_number <= page_end)
    pages = list(db.scalars(query.order_by(DocumentPage.page_number)))
    if sum(len(page.text.encode("utf-8")) for page in pages) > MAX_GRAPH_TEXT_BYTES:
        raise ValueError("Selected document text exceeds the graph size limit.")

    key_terms = list(
        db.scalars(
            select(DocumentKeyTerm).where(DocumentKeyTerm.document_id == document.id)
        )
    )
    glossary_terms = list(
        db.scalars(
            select(GlossaryTerm).where(
                GlossaryTerm.document_id == document.id,
                GlossaryTerm.owner_id == owner_id,
            )
        )
    )
    scope = f"{page_start or '*'}:{page_end or '*'}"
    version_data = {
        "version": GRAPH_VERSION,
        "pages": [(page.page_number, page.text) for page in pages],
        "terms": [
            (term.term, term.label, term.page, term.source) for term in key_terms
        ],
        "glossary": [
            (term.term, term.definition, term.page, term.importance)
            for term in glossary_terms
        ],
        "max_nodes": max_nodes,
    }
    version = sha256(
        json.dumps(version_data, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()
    cache_key = (document.id, scope, version)
    if relation_provider is None and cache_key in _GRAPH_CACHE:
        return deepcopy(_GRAPH_CACHE[cache_key])

    nodes = _build_nodes(
        pages=pages,
        key_terms=key_terms,
        glossary_terms=glossary_terms,
        max_nodes=max_nodes,
    )
    edges, connected = _make_edges(nodes, pages)
    nodes = [node for node in nodes if node["id"] in connected]
    node_ids = {node["id"] for node in nodes}
    edges = [
        edge
        for edge in edges
        if edge["source"] in node_ids and edge["target"] in node_ids
    ]
    if relation_provider is not None:
        edges = _label_relations(edges, relation_provider)
    result = {
        "document_id": document.id,
        "scope": scope,
        "version": version,
        "nodes": [
            {key: value for key, value in node.items() if key != "definition"}
            for node in nodes
        ],
        "edges": edges,
    }
    if relation_provider is None:
        if len(_GRAPH_CACHE) >= 128:
            _GRAPH_CACHE.pop(next(iter(_GRAPH_CACHE)))
        _GRAPH_CACHE[cache_key] = deepcopy(result)
    return result


def get_graph_node_detail(
    graph: dict[str, Any], node_id: str, definitions: dict[str, str]
) -> dict[str, Any] | None:
    """Return one graph node with its glossary definition and cited neighbours."""
    node = next((item for item in graph["nodes"] if item["id"] == node_id), None)
    if node is None:
        return None
    neighbours = []
    for edge in graph["edges"]:
        if edge["source"] == node_id:
            neighbour_id = edge["target"]
        elif edge["target"] == node_id:
            neighbour_id = edge["source"]
        else:
            continue
        neighbour = next(item for item in graph["nodes"] if item["id"] == neighbour_id)
        neighbours.append({**neighbour, **edge})
    return {
        **node,
        "definition": definitions.get(node_id),
        "neighbours": neighbours,
    }


def graph_definitions(
    db: Session,
    *,
    document_id: int,
    owner_id: int,
    nodes: list[dict[str, Any]],
) -> dict[str, str]:
    """Load glossary definitions or source-backed sentences for graph nodes."""
    rows = list(
        db.scalars(
            select(GlossaryTerm).where(
                GlossaryTerm.document_id == document_id,
                GlossaryTerm.owner_id == owner_id,
            )
        )
    )
    definitions = {
        _node_id(normalize_term(term.term)): term.definition for term in rows
    }
    pages = list(
        db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_number)
        )
    )
    for node in nodes:
        if node["id"] in definitions:
            continue
        definitions[node["id"]] = next(
            (
                sentence
                for page in pages
                if page.page_number in node["pages"]
                if (sentence := find_evidence_sentence(page.text, node["label"]))
            ),
            "",
        )
    return definitions


def clear_graph_cache() -> None:
    """Clear the process-local graph cache for tests and administrative refreshes."""
    _GRAPH_CACHE.clear()
