"""Split extracted text into overlapping chunks for embedding.

Chunks never cross a page or section boundary, so each one has exactly one citation
location. Inside a block, a cut is placed at the nearest paragraph break, then sentence
end, then space within the last part of the window, so chunks rarely end mid-sentence.
"""

import re
from dataclasses import dataclass

from app.rag.extraction import TextBlock

# A block shorter than this (typically a lone parent heading) is merged into the next.
MIN_BLOCK_CHARS = 40
# Look for a natural break only in the last 40% of the window.
_BREAK_SEARCH_START = 0.6
# Ends of sentences: punctuation followed by whitespace.
_SENTENCE_BREAK = re.compile(r"[.!?][\"')\]]?\s")


@dataclass
class ChunkSpec:
    content: str
    page_number: int | None
    section: str | None
    char_start: int  # offsets into the whole document text
    char_end: int


def _find_break(text: str, start: int, end: int) -> int:
    """Best cut position in text[start:end], searching backwards from end."""
    window_start = start + int((end - start) * _BREAK_SEARCH_START)
    paragraph = text.rfind("\n\n", window_start, end)
    if paragraph != -1:
        return paragraph + 2
    sentence_ends = [m.end() for m in _SENTENCE_BREAK.finditer(text, window_start, end)]
    if sentence_ends:
        return sentence_ends[-1]
    newline = text.rfind("\n", window_start, end)
    if newline != -1:
        return newline + 1
    space = text.rfind(" ", window_start, end)
    if space != -1:
        return space + 1
    return end  # one enormous word: hard cut


def split_text(text: str, chunk_size: int, overlap: int) -> list[tuple[int, int]]:
    """Return (start, end) spans covering ``text``; consecutive spans overlap."""
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")
    spans: list[tuple[int, int]] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            end = _find_break(text, start, end)
        spans.append((start, end))
        if end >= length:
            break
        next_start = max(end - overlap, start + 1)
        # Start the next chunk at a word boundary, not in the middle of a word.
        while next_start < end and not text[next_start - 1].isspace():
            next_start += 1
        start = next_start if next_start < end else end
    return spans


def _merge_tiny_blocks(blocks: list[TextBlock]) -> list[TextBlock]:
    """Fold very short blocks (lone headings) into the following block of the same page.

    Blocks on different pages are never merged, so page citations stay exact.
    """
    merged: list[TextBlock] = []
    carry: TextBlock | None = None
    for position, block in enumerate(blocks):
        if carry is not None and carry.page_number != block.page_number:
            merged.append(carry)
            carry = None
        text = f"{carry.text}\n{block.text}" if carry is not None else block.text
        carry = None
        next_block = blocks[position + 1] if position + 1 < len(blocks) else None
        current = TextBlock(text=text, page_number=block.page_number, section=block.section)
        if (
            len(text) < MIN_BLOCK_CHARS
            and next_block is not None
            and next_block.page_number == block.page_number
        ):
            carry = current
            continue
        merged.append(current)
    if carry is not None:
        merged.append(carry)
    return merged


def chunk_blocks(blocks: list[TextBlock], chunk_size: int, overlap: int) -> list[ChunkSpec]:
    chunks: list[ChunkSpec] = []
    document_offset = 0
    for block in _merge_tiny_blocks(blocks):
        for start, end in split_text(block.text, chunk_size, overlap):
            raw = block.text[start:end]
            content = raw.strip()
            if not content:
                continue
            leading = len(raw) - len(raw.lstrip())
            chunk_start = document_offset + start + leading
            chunks.append(
                ChunkSpec(
                    content=content,
                    page_number=block.page_number,
                    section=block.section,
                    char_start=chunk_start,
                    char_end=chunk_start + len(content),
                )
            )
        document_offset += len(block.text) + 2  # blocks are joined by a blank line
    return chunks
