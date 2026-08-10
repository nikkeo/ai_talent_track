"""Проверка ответа перед отправкой. Владелец: Agent B, блок 2."""

from .contracts import Draft, PolicyDecision, RetrievalResult, Validation


def validate(draft: Draft, retrieval: RetrievalResult, policy: PolicyDecision) -> Validation:
    """Citation, отсутствие PII и плейсхолдеров, запрещённые обещания, длина, allow_auto_send."""
    return Validation(ok=False, failed_checks=["not_implemented"])
