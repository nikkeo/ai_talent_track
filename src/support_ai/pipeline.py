"""Оркестрация обработки тикета. Владелец: Agent A, блок 2."""

from .contracts import AuditEvent, Decision, Ticket


def process(
    ticket: Ticket,
    *,
    llm_mode: str = "mock",
    faults: frozenset[str] = frozenset(),
) -> tuple[Decision, AuditEvent]:
    """normalize -> redact -> classify -> policy -> retrieval -> generate -> validate -> audit.

    faults: {"llm", "policy", "retrieval", "audit"} — инъекция отказов для тестов и демо.
    """
    raise NotImplementedError("Agent A, блок 2")
