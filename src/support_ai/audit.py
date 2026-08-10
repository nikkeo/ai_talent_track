"""Журнал автоматических решений. Нет записи — нет автодействия. Владелец: Agent A, блок 2."""

from .contracts import AuditEvent


def write(event: AuditEvent) -> bool:
    """Append JSONL в config.AUDIT_PATH. При ошибке возвращает False, не бросает исключение."""
    raise NotImplementedError("Agent A, блок 2")
