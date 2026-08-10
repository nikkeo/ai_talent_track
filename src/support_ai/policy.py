"""Детерминированная бизнес-policy. Приоритет над прогнозом модели. Владелец: Agent A, блок 2."""

from .contracts import Classification, PolicyContext, PolicyDecision


def decide(cls: Classification, text: str, ctx: PolicyContext) -> PolicyDecision:
    """Правила SEC-001 / PRIV-001 / LEG-001 / FIN-001 / LOW-001 / AUTO-001 / DEFAULT.

    Возвращает ровно один route: ESCALATE | DRAFT_ONLY | AUTO_CANDIDATE.
    """
    raise NotImplementedError("Agent A, блок 2")


def policy_available() -> bool:
    """Точка инъекции отказа: недоступная policy запрещает любую автоматизацию."""
    return True
