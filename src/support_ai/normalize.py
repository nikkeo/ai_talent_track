"""Нормализация текста тикета. Владелец: Agent A, блок 1."""

from .contracts import Ticket


def normalize(ticket: Ticket) -> str:
    """HTML, email-цитирование, подписи, пробелы, обрезка до MAX_TICKET_CHARS."""
    raise NotImplementedError("Agent A, блок 1")
