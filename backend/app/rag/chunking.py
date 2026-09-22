from __future__ import annotations

import hashlib
import re
from app.rag.models import Block, Chunk, ParsedDocument


TOKEN = re.compile(r'\S+')


def token_count(text: str) -> int:
    return len(TOKEN.findall(text))


class StructureAwareChunker:
    def __init__(self, size: int = 750, overlap: int = 100):
        if size < 50 or overlap < 0 or overlap >= size:
            raise ValueError('Chunk size must be at least 50 and overlap must be smaller than size.')
        self.size, self.overlap = size, overlap

    def _split_large(self, block: Block) -> list[Block]:
        words = TOKEN.findall(block.text)
        if len(words) <= self.size:
            return [block]
        step = self.size - self.overlap
        return [
            Block(' '.join(words[start:start + self.size]), block.page_number, block.section, block.kind)
            for start in range(0, len(words), step)
            if words[start:start + self.size]
        ]

    def chunk(self, document: ParsedDocument) -> list[Chunk]:
        pieces = [piece for block in document.blocks for piece in self._split_large(block)]
        chunks: list[Chunk] = []
        current: list[Block] = []
        current_tokens = 0

        def flush():
            nonlocal current, current_tokens
            if not current:
                return
            text = '\n\n'.join(item.text for item in current).strip()
            pages = {item.page_number for item in current if item.page_number is not None}
            sections = [item.section for item in current if item.section]
            chunk = Chunk(
                text=text,
                chunk_index=len(chunks),
                page_number=next(iter(pages)) if len(pages) == 1 else None,
                section=sections[0] if sections and all(s == sections[0] for s in sections) else None,
                chunk_hash=hashlib.sha256(text.encode('utf-8')).hexdigest(),
            )
            chunks.append(chunk)
            carry: list[Block] = []
            carried = 0
            for item in reversed(current):
                count = token_count(item.text)
                if carry and carried + count > self.overlap:
                    break
                carry.insert(0, item)
                carried += count
                if carried >= self.overlap:
                    break
            current, current_tokens = carry, carried

        for piece in pieces:
            count = token_count(piece.text)
            boundary = current and (
                current_tokens + count > self.size
                or (piece.page_number is not None and current[-1].page_number is not None and piece.page_number != current[-1].page_number)
            )
            if boundary:
                flush()
            current.append(piece)
            current_tokens += count
        flush()
        return chunks
