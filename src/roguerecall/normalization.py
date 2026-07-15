from __future__ import annotations

import unicodedata
from dataclasses import dataclass

import regex  # type: ignore[import-untyped]


_WORD_SEGMENTS = regex.compile(
    r"\b.*?\b", regex.WORD | regex.VERSION1 | regex.DOTALL
)


@dataclass(frozen=True)
class NormalizedWord:
    value: str
    raw_start: int
    raw_end: int
    raw_line: int


def prose_words(text: str) -> list[NormalizedWord]:
    """Apply the V1 UAX #29/NFC/full-case-fold prose profile."""

    words: list[NormalizedWord] = []
    for match in _WORD_SEGMENTS.finditer(text):
        raw = match.group()
        if not raw or not any(unicodedata.category(char)[0] in {"L", "N"} for char in raw):
            continue
        normalized = _normalize_line_endings(raw)
        value = unicodedata.normalize(
            "NFC", unicodedata.normalize("NFC", normalized).casefold()
        )
        words.append(
            NormalizedWord(
                value=value,
                raw_start=match.start(),
                raw_end=match.end(),
                raw_line=_normalize_line_endings(text[: match.start()]).count("\n"),
            )
        )
    return words


def prose_values(text: str) -> list[str]:
    return [word.value for word in prose_words(text)]


def normalized_lines(text: str) -> list[str]:
    return _normalize_line_endings(text).split("\n")


def _normalize_line_endings(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")
