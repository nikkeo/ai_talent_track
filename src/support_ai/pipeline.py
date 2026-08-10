"""Оркестрация обработки тикета. Владелец: Agent A, блок 2.

Синхронный контур заканчивается после policy — это архитектурная граница,
а не деталь реализации: бюджет <500 мс измеряется на route() отдельно.
Исходный Ticket не покидает route(): дальше идёт только SanitizedTicket.
"""

from .contracts import AuditEvent, Decision, RoutingOutcome, Ticket


def route(ticket: Ticket, *, faults: frozenset[str] = frozenset()) -> RoutingOutcome:
    """СИНХРОННО: normalize -> redact -> classify -> policy -> persist audit -> маршрут.

    Не вызывает ни retrieval, ни LLM. Пишет audit-событие ROUTING_DECIDED.
    Бюджет <500 мс, замеряется в RoutingDecision.sync_route_ms.
    """
    raise NotImplementedError("Agent A, блок 2")


def fulfill(
    outcome: RoutingOutcome,
    *,
    llm_mode: str = "mock",
    faults: frozenset[str] = frozenset(),
) -> tuple[Decision, AuditEvent]:
    """АСИНХРОННО (в PoC — inline): retrieval -> draft -> validate -> persist audit -> действие.

    Вызывается только при outcome.policy.route in {DRAFT_ONLY, AUTO_CANDIDATE}.
    Работает с outcome.sanitized; доступа к исходному тексту здесь нет.
    Пишет audit-событие FULFILLMENT_COMPLETED с sequence = 2.
    """
    raise NotImplementedError("Agent A, блок 2")


def process(
    ticket: Ticket,
    *,
    llm_mode: str = "mock",
    faults: frozenset[str] = frozenset(),
) -> tuple[Decision, AuditEvent]:
    """Оба контура подряд — удобство демо и тестов. Границу CLI печатает явно.

    faults: {"llm", "policy", "retrieval", "audit"} — инъекция отказов.
    Идемпотентность по ticket.idempotency_key: повтор возвращает первое решение,
    не запускает LLM и не пишет второе audit-событие.
    """
    raise NotImplementedError("Agent A, блок 2")
