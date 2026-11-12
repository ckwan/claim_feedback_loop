"""Splitting notes into pieces small enough to embed well.

Most claim notes are a sentence or two and stay whole. Longer notes are split on
sentence boundaries, so a chunk never ends mid thought, with one sentence of overlap
so a fact near a boundary appears in both neighbours.
"""
from __future__ import annotations

import re

DEFAULT_MAX_CHARS = 500
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def chunk_text(text: str | None, max_chars: int = DEFAULT_MAX_CHARS, overlap_sentences: int = 1) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sentences = []
    for sentence in _SENTENCE_END.split(text):
        # A single very long sentence is cut on word boundaries.
        while len(sentence) > max_chars:
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            sentences.append(sentence[:cut])
            sentence = sentence[cut:].lstrip()
        if sentence:
            sentences.append(sentence)

    chunks: list[list[str]] = []
    current: list[str] = []
    for sentence in sentences:
        candidate = " ".join(current + [sentence])
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = current[-overlap_sentences:] if overlap_sentences else []
            # The overlap itself must fit alongside the new sentence.
            while current and len(" ".join(current + [sentence])) > max_chars:
                current = current[1:]
        current = current + [sentence]
    if current:
        chunks.append(current)
    return [" ".join(parts) for parts in chunks]
