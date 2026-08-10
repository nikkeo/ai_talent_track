"""Нормализация текста тикета. Владелец: Agent A, блок 1."""

import html
import re

from .contracts import Ticket
from .config import MAX_TICKET_CHARS


_HTML_TAG = re.compile(r"<[^>]*>")
_REPLY_MARKER = re.compile(
    r"^(?:>+|On\s+.+\s+wrote:|-----Original Message-----)\s*$",
    re.IGNORECASE,
)


def detect_language(text: str) -> str:
    """Определяет русский язык по доле кириллицы среди букв."""
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return "unknown"
    cyrillic = sum("а" <= char.lower() <= "я" or char.lower() == "ё" for char in letters)
    return "ru" if cyrillic / len(letters) >= 0.5 else "other"


def normalize(ticket: Ticket) -> str:
    """HTML, email-цитирование, подписи, пробелы, обрезка до MAX_TICKET_CHARS."""
    text = html.unescape(_HTML_TAG.sub(" ", ticket.text))
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "--" or _REPLY_MARKER.match(stripped):
            break
        kept.append(line)
    return " ".join(" ".join(kept).split())[:MAX_TICKET_CHARS]
