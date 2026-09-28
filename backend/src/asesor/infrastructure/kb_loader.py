import hashlib
import re
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from asesor.domain.enums import KbCategory

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_HEADING = re.compile(r"^##\s+(.+)$", re.MULTILINE)

# ~4 characters per token in Spanish: 400-700 tokens from the spec ≈ 1600-2800 characters.
MAX_CHARS = 2800
MIN_CHARS = 400
OVERLAP_CHARS = 200


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    title: str
    category: KbCategory
    source: str
    body: str


@dataclass(frozen=True, slots=True)
class LoadedChunk:
    chunk_id: str
    title: str
    category: KbCategory
    source: str
    content: str
    content_hash: str


class KbFormatError(ValueError):
    pass


def parse_document(path: Path) -> ParsedDocument:
    raw = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(raw)
    if match is None:
        raise KbFormatError(f"{path.name}: missing frontmatter with title and categoria")

    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip('"')

    title = fields.get("title")
    category = fields.get("categoria")
    if not title or not category:
        raise KbFormatError(f"{path.name}: frontmatter needs title and categoria")

    try:
        parsed_category = KbCategory(category)
    except ValueError as exc:
        raise KbFormatError(f"{path.name}: categoria '{category}' is not valid") from exc

    return ParsedDocument(
        title=title,
        category=parsed_category,
        source=path.name,
        body=raw[match.end() :].strip(),
    )


def split_by_headings(body: str) -> list[str]:
    """Splits by level-2 headings, merging ones that are too short and
    splitting ones that are too long."""
    positions = [match.start() for match in _HEADING.finditer(body)]
    if not positions:
        sections = [body]
    else:
        bounds = [0, *positions, len(body)] if positions[0] != 0 else [*positions, len(body)]
        sections = [body[start:end].strip() for start, end in pairwise(bounds)]
        sections = [section for section in sections if section]

    merged: list[str] = []
    for section in sections:
        if merged and len(merged[-1]) < MIN_CHARS:
            merged[-1] = f"{merged[-1]}\n\n{section}"
        else:
            merged.append(section)

    chunks: list[str] = []
    for section in merged:
        chunks.extend(_split_long(section))
    return chunks


def _split_long(section: str) -> list[str]:
    if len(section) <= MAX_CHARS:
        return [section]

    pieces: list[str] = []
    start = 0
    while start < len(section):
        end = min(start + MAX_CHARS, len(section))
        if end < len(section):
            breakpoint_ = section.rfind("\n", start + MIN_CHARS, end)
            if breakpoint_ != -1:
                end = breakpoint_
        pieces.append(section[start:end].strip())
        if end >= len(section):
            break
        start = max(end - OVERLAP_CHARS, start + 1)

    return [piece for piece in pieces if piece]


def load_chunks(kb_dir: Path) -> list[LoadedChunk]:
    chunks: list[LoadedChunk] = []

    for path in sorted(kb_dir.glob("*.md")):
        document = parse_document(path)
        for index, content in enumerate(split_by_headings(document.body)):
            chunks.append(
                LoadedChunk(
                    chunk_id=f"{path.stem}#{index:02d}",
                    title=document.title,
                    category=document.category,
                    source=document.source,
                    content=content,
                    content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                )
            )

    return chunks
