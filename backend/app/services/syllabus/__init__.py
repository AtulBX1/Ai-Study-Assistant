"""Private syllabus parsing, mapping, and coverage services."""

import re
from collections.abc import Sequence

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Chunk, ChunkTopic, Document, Syllabus, SyllabusTopic


def parse_syllabus(text: str) -> list[dict]:
    """Parse common numbered/indented syllabus lines into a nested tree."""
    roots: list[dict] = []
    stack: list[tuple[int, dict, tuple[int, ...] | None, bool]] = []
    bullet = re.compile(r"^\s*(?:[-*•▪◦]|\d+[.)])\s+(.+)$")
    numbered = re.compile(
        r"^\s*(?:unit\s+([ivxlcdm]+)\s*[:.)-]?|((?:\d+\.)*\d+)[.)]?)\s*(.*)$", re.I
    )
    for raw in text.splitlines():
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" \t"))
        line = raw.strip()
        match = numbered.match(line)
        path: tuple[int, ...] | None = None
        is_unit = False
        if match:
            marker, numeric, rest = match.groups()
            title = rest.strip() or line
            if marker:
                path = (100 + "ivxlcdm".find(marker.casefold()[0]),)
                is_unit = True
            elif numeric:
                path = tuple(int(part) for part in numeric.rstrip(".").split("."))
        else:
            matched = bullet.match(raw)
            title = matched.group(1).strip() if matched else line
        parts = [
            part.strip(" .;:")
            for part in re.split(r"[,;]", title)
            if part.strip(" .;:")
        ]
        if not parts:
            continue
        title, *subs = parts
        if path:
            depth = len(path)
            while (
                stack
                and not (stack[-1][3] and not is_unit)
                and (
                    stack[-1][0] >= depth
                    or (stack[-1][2] and not stack[-1][3] and stack[-1][2] >= path)
                )
            ):
                stack.pop()
        else:
            depth = (stack[-1][0] + 1) if stack else 1
            while (
                stack
                and not stack[-1][3]
                and indent <= stack[-1][0]
                and stack[-1][2] is None
            ):
                stack.pop()
        node = {
            "title": title,
            "order": len(stack[-1][1]["children"]) if stack else len(roots),
            "keywords": [],
            "sub_topics": subs,
            "children": [],
        }
        if stack:
            stack[-1][1]["children"].append(node)
        else:
            roots.append(node)
        stack.append((depth if path is None else len(path), node, path, is_unit))
    return roots


def flatten_tree(tree: Sequence[dict], parent_id: int | None = None):
    for node in tree:
        yield node, parent_id
        yield from flatten_tree(node.get("children", []), node.get("_id"))


def save_tree(db: Session, syllabus: Syllabus, tree: list[dict]) -> None:
    db.execute(delete(SyllabusTopic).where(SyllabusTopic.syllabus_id == syllabus.id))

    def add(nodes: list[dict], parent: int | None = None):
        for order, node in enumerate(nodes):
            topic = SyllabusTopic(
                syllabus_id=syllabus.id,
                parent_id=parent,
                title=node["title"][:255],
                order=node.get("order", order),
                keywords=node.get("keywords", []),
                sub_topics=node.get("sub_topics", []),
            )
            db.add(topic)
            db.flush()
            add(node.get("children", []), topic.id)

    add(tree)


def remap_syllabus(
    db: Session, syllabus: Syllabus, owner_id: int, embedder, threshold: float = 0.35
) -> int:
    """Map each owned ready-document chunk to its best one or two topics."""
    topics = list(
        db.scalars(
            select(SyllabusTopic).where(SyllabusTopic.syllabus_id == syllabus.id)
        )
    )
    chunks = list(
        db.scalars(
            select(Chunk)
            .join(Document, Chunk.doc_id == Document.id)
            .where(Document.owner_id == owner_id, Document.status == "ready")
        )
    )
    if not topics or not chunks:
        return 0
    topic_text = [
        " ".join([topic.title, *topic.keywords, *topic.sub_topics]) for topic in topics
    ]
    vectors = np.asarray(
        embedder.embed_texts([chunk.text for chunk in chunks] + topic_text), dtype=float
    )
    chunk_vectors, topic_vectors = vectors[: len(chunks)], vectors[len(chunks) :]
    matrix = chunk_vectors @ topic_vectors.T
    added = 0
    for chunk, scores in zip(chunks, matrix, strict=True):
        existing = list(
            db.scalars(
                select(ChunkTopic).where(
                    ChunkTopic.chunk_id == chunk.id,
                    ChunkTopic.topic_id.in_([t.id for t in topics]),
                )
            )
        )
        manual = {item.topic_id for item in existing if item.source == "manual"}
        for item in existing:
            if item.source == "auto":
                db.delete(item)
        if manual:
            continue
        candidates = sorted(enumerate(scores), key=lambda pair: pair[1], reverse=True)
        selected = 0
        for index, score in candidates:
            topic = topics[index]
            if topic.id in manual or score < threshold:
                continue
            db.add(
                ChunkTopic(
                    chunk_id=chunk.id,
                    topic_id=topic.id,
                    score=float(score),
                    source="auto",
                )
            )
            added += 1
            selected += 1
            if selected >= 2:
                break
    db.flush()
    return added


def coverage(db: Session, syllabus_id: int) -> dict:
    topics = list(
        db.scalars(
            select(SyllabusTopic)
            .where(SyllabusTopic.syllabus_id == syllabus_id)
            .order_by(SyllabusTopic.order)
        )
    )
    result = []
    for topic in topics:
        rows = list(
            db.execute(
                select(ChunkTopic, Chunk)
                .join(Chunk, ChunkTopic.chunk_id == Chunk.id)
                .where(ChunkTopic.topic_id == topic.id)
            )
        )
        chunks = {chunk.id: chunk for _, chunk in rows}
        pages = sorted(
            {
                page
                for mapping, chunk in rows
                for page in range(
                    mapping.page_start or chunk.page_start,
                    (mapping.page_end or chunk.page_end) + 1,
                )
            }
        )
        documents = sorted({chunk.doc_id for _, chunk in rows})
        status = (
            "no material" if not chunks else "thin" if len(chunks) < 3 else "covered"
        )
        result.append(
            {
                "topic_id": topic.id,
                "title": topic.title,
                "chunks": len(chunks),
                "pages": pages,
                "documents": documents,
                "status": status,
            }
        )
    covered = sum(item["status"] == "covered" for item in result)
    return {
        "topics": result,
        "percent": round(covered / len(result) * 100, 2) if result else 0.0,
    }
