"""Read-only, structural exercise lookup ahead of semantic retrieval.

Only completed parses of PDFs actually present in the selected KB are read.
No OCR, model call, index write, or global cross-KB search is performed here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import unicodedata

from deeptutor.services.parsing.cache import source_hash_from_path

MAX_QUESTIONS = 30
MAX_CONTENT = 24000
_SKIP = {"header", "footer", "page_header", "page_footer", "page_number"}
_PAIR = re.compile(r"(?<![\dA-Za-z.])(\d{1,3})\s*[-.]\s*(\d{1,3})(?!\d|[.-]\d)")
_CHAPTER = re.compile(r"chapter\s*(\d+)", re.I)
_START = re.compile(r"^\s*(?:(\d{1,3})\s*[-.]\s*(\d{1,3})[.\u3001]?\s*|(\d{1,3})[.\u3001]\s+)(?=\S)")
_INTENT = re.compile(
    r"problem|exercise|question|solution|solve", re.I
)


def _normal(text: str) -> str:
    return unicodedata.normalize("NFKC", text).translate(str.maketrans("—–−\uff0d", "----"))


def _number(text: str) -> int:
    if text.isdigit():
        return int(text)
    return 0


def requested_exercises(query: str) -> tuple[list[tuple[int, int]], str | None]:
    """Do not interpret formula/figure/section queries or arithmetic as exercises."""
    query = _normal(query)
    explicit = bool(_INTENT.search(query))
    if not explicit and re.search(
        r"formula|section|equation|figure", query, re.I
    ):
        return [], None
    matches = list(_PAIR.finditer(query))
    bare = re.sub(r"[\d\s.,\u3001;:()\-]+", "", query) == ""
    lookup_request = bool(re.search(r"lookup|find|search", query, re.I))
    if not explicit and not bare and not lookup_request:
        return [], None
    keys = []
    for match in matches:
        key = (int(match[1]), int(match[2]))
        if all(key) and key not in keys:
            keys.append(key)
    chapter = _CHAPTER.search(query)
    if not keys and chapter:
        for match in re.finditer(r"(?:question|exercise|problem)\s*(\d{1,3})", query[chapter.end() :], re.I):
            key = (_number(chapter[1]), int(match[1]))
            if all(key) and key not in keys:
                keys.append(key)
    # Bounded explicit ranges, e.g. 2-13 to 2-15.
    for left, right in zip(matches, matches[1:]):
        if re.fullmatch(r"\s*(?:to|through|~)\s*", query[left.end() : right.start()], re.I):
            a, b = (int(left[1]), int(left[2])), (int(right[1]), int(right[2]))
            if a[0] == b[0] and 0 < b[1] - a[1] < MAX_QUESTIONS:
                pos = keys.index(a)
                keys[pos : pos + 1] = [(a[0], n) for n in range(a[1], b[1])]
    kind = (
        "Review questions"
        if re.search(r"review questions|thought questions", query, re.I)
        else "Exercises"
        if re.search(r"exercise", query, re.I)
        else None
    )
    return list(dict.fromkeys(keys)), kind


def _text(block: dict[str, Any]) -> str:
    parts = []
    for key in (
        "text",
        "content",
        "body",
        "code_body",
        "table_body",
        "image_caption",
        "image_footnote",
        "table_caption",
        "table_footnote",
    ):
        value = block.get(key)
        if isinstance(value, list):
            value = "\n".join(str(v) for v in value)
        if isinstance(value, str) and value.strip() and value.strip() not in parts:
            parts.append(value.strip())
    return "\n\n".join(parts)


def _page(block: dict[str, Any]) -> int | None:
    try:
        return (
            int(block["original_page"])
            if block.get("original_page") is not None
            else int(block["page_idx"]) + 1
        )
    except (KeyError, TypeError, ValueError):
        return None


@dataclass
class Exercise:
    """One numbered exercise and its contiguous parsed source blocks."""

    chapter: int
    number: int
    kind: str
    ordinal: int
    parts: list[str] = field(default_factory=list)
    pages: set[int] = field(default_factory=set)
    images: bool = False


def collect_exercises(blocks: list[dict[str, Any]]) -> list[Exercise]:
    """Join problem text, equations and tables within exercise sections."""
    chapter = 0
    section_chapter = None
    kind = None
    current = None
    exercises = []
    for ordinal, block in enumerate(blocks):
        if not isinstance(block, dict) or block.get("type") in _SKIP:
            continue
        text = _text(block)
        normal = _normal(text)
        compact = re.sub(r"\s+", "", normal)
        # TOC lines are not chapter boundaries or exercise headings.
        toc = "……" in text or "..." in text or "…" in text
        heading = _CHAPTER.match(normal)
        chapter_title = heading and (
            block.get("text_level") or not re.search(r"[\d\u3002,$\uff0c]", normal[heading.end() :])
        )
        if chapter_title and not toc and len(text) < 100 and "\n" not in text:
            chapter = _number(heading[1])
            kind = None
            current = None
            continue
        if compact.casefold() in {"exercises", "problems", "reviewquestions"}:
            kind = "Review questions" if compact.casefold() == "reviewquestions" else "Exercises"
            current = None
            section_chapter = None
            continue
        if not kind:
            continue
        caption = re.fullmatch(r"(?:Exercises|Review questions)\s*(\d+)\s*[-.]\s*(\d+)", normal, re.I)
        if caption and block.get("type") != "image":
            # OCR occasionally drops the next question's opening paragraph.
            # A later question's figure caption still gives us a boundary;
            # never append its continuation to the preceding problem.
            if current and int(caption[1]) == current.chapter and int(caption[2]) > current.number:
                current = None
            continue
        # A new numbered section ends the exercise area even when OCR omitted
        # the intervening chapter title (common in image-based title pages).
        if block.get("text_level") and _START.match(normal):
            kind = None
            current = None
            continue
        if block.get("type") == "image":
            if current is not None:
                labels = [(int(m[1]), int(m[2])) for m in _PAIR.finditer(normal)]
                if labels and (current.chapter, current.number) not in labels:
                    if any(c == current.chapter and n > current.number for c, n in labels):
                        current = None
                    continue
                current.images = True
                if _page(block) is not None:
                    current.pages.add(_page(block))
            # Captions are image metadata, never the start of another exercise.
            continue
        if toc:
            current = None
            kind = None
            continue
        if not text or re.fullmatch(r"\d+", text):
            continue
        # Some parsers put consecutive numbered problems in one text block.
        pieces = (
            re.split(r"\n(?=\s*\d{1,3}(?:[-.]\d{1,3}[.\u3001]?\s*|[.\u3001]\s+)\S)", text)
            if block.get("type") == "text"
            else [text]
        )
        for piece in pieces:
            match = _START.match(_normal(piece)) if block.get("type") == "text" else None
            if match:
                c = int(match[1]) if match[1] else chapter
                n = int(match[2] or match[3])
                # A different chapter here is usually a decimal measurement.
                if c and n and (section_chapter is None or c == section_chapter):
                    chapter = c
                    section_chapter = c
                    current = Exercise(c, n, kind, ordinal)
                    exercises.append(current)
            if current is not None:
                current.parts.append(piece)
                if _page(block) is not None:
                    current.pages.add(_page(block))
    return exercises


@lru_cache(maxsize=32)
def _source_hash(path: str, mtime: int, size: int) -> str:
    # mtime and size invalidate the bounded cache when a source changes.
    return source_hash_from_path(Path(path))


@lru_cache(maxsize=8)
def _parsed(path: str, mtime: int, size: int) -> tuple[Exercise, ...]:
    blocks = json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(collect_exercises(blocks)) if isinstance(blocks, list) else ()


def _parse_for(source: Path, cache_root: Path) -> Path | None:
    stat = source.stat()
    digest = _source_hash(str(source), stat.st_mtime_ns, stat.st_size)
    root = cache_root / digest[:2] / digest
    manifests = sorted(
        root.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True
    )
    for manifest in manifests:
        if manifest.parent.name.startswith(".") or not manifest.resolve().is_relative_to(
            cache_root.resolve()
        ):
            continue
        try:
            meta = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(meta, dict) or meta.get("source_hash") != digest:
                continue
            files = sorted(manifest.parent.rglob("*_content_list.json"))
            files = [
                p
                for p in files
                if not any(s.startswith(".") for s in p.relative_to(manifest.parent).parts)
                and p.resolve().is_relative_to(manifest.parent.resolve())
            ]
            full = [p for p in files if p.name == "full_content_list.json"]
            if full or files:
                return (full or files)[0]
        except (OSError, ValueError, TypeError):
            continue
    return None


def lookup_exercises(query: str, kb_dir: Path, cache_root: Path) -> dict[str, Any] | None:
    """Return exact candidates from ready PDF parses, or allow normal retrieval.

    Sources must belong to the selected KB. Missing structured parses return
    ``None``; supported parses report each number as found, ambiguous or absent.
    No parse, index, embedding or settings files are created or modified.
    """
    keys, kind = requested_exercises(query)
    if not keys:
        return None
    if len(keys) > MAX_QUESTIONS:
        content = f"This request contains {len(keys)} question numbers. Retrieve them in batches of at most {MAX_QUESTIONS} to preserve complete stems."
        return {
            "query": query,
            "answer": content,
            "content": content,
            "sources": [],
            "provider": "llamaindex",
            "retrieval_method": "exercise_exact",
            "exercise_status": [],
        }
    candidates = {key: [] for key in keys}
    supported = False
    raw = kb_dir / "raw"
    for source in sorted(raw.glob("*.pdf")):
        if not source.resolve().is_relative_to(raw.resolve()):
            continue
        try:
            parsed = _parse_for(source, cache_root)
            if parsed is None:
                continue
            stat = parsed.stat()
            exercises = _parsed(str(parsed), stat.st_mtime_ns, stat.st_size)
            if not exercises:
                continue
            supported = True
            for exercise in exercises:
                key = (exercise.chapter, exercise.number)
                if key in candidates and (kind is None or exercise.kind == kind):
                    candidates[key].append((source, exercise))
        except (OSError, ValueError, TypeError):
            continue
    if not supported:
        return None
    parts = [
        "The following results locate parsed source text by question number. A missing match does not establish absence from the original book. Do not substitute figure numbers, equation numbers or similar questions."
    ]
    sources = []
    statuses = []
    for key, matches in candidates.items():
        label = f"{key[0]}-{key[1]}"
        status = "ambiguous" if len(matches) > 1 else "found" if matches else "not_found"
        statuses.append({"question": label, "status": status, "matches": len(matches)})
        if not matches:
            parts.append(
                f"[{label}] was not located in the parsed exercise/review section. Check the book, chapter and question type, and inspect original pages when needed."
            )
            continue
        if len(matches) > 1:
            parts.append(
                f"[{label}] has {len(matches)} candidates. Each identifies its book and question type; do not combine their stems."
            )
        for source, exercise in matches[:4]:
            pages = sorted(exercise.pages)
            page_label = ", ".join(map(str, pages)) or "unknown"
            text = "\n\n".join(exercise.parts)
            title = f"{source.name} | {exercise.kind} {label} | PDF page {page_label}"
            note = (
                ""
                if exercise.images
                else ""
            )
            excerpt = f"[{title}]\n{text}{note}"
            if sum(map(len, parts)) + len(excerpt) > MAX_CONTENT:
                parts.append(
                    f"[{label}] exceeds this response limit. Select fewer question numbers or inspect original PDF page {page_label}."
                )
                statuses[-1]["status"] = "needs_single_query"
                continue
            parts.append(excerpt)
            chunk_id = (
                "exercise-"
                + hashlib.sha256(
                    f"{source}:{key}:{exercise.kind}:{exercise.ordinal}".encode()
                ).hexdigest()[:20]
            )
            sources.append(
                {
                    "title": title,
                    "content": text[:200],
                    "source": str(source),
                    "page": page_label,
                    "chunk_id": chunk_id,
                    "score": 1.0,
                    "question_number": label,
                    "exercise_kind": exercise.kind,
                    "requires_page_review": exercise.images,
                }
            )
    content = "\n\n".join(parts)
    return {
        "query": query,
        "answer": content,
        "content": content,
        "sources": sources,
        "provider": "llamaindex",
        "retrieval_method": "exercise_exact",
        "exercise_status": statuses,
    }
