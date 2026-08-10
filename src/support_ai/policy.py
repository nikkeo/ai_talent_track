"""Детерминированная бизнес-policy. Приоритет над прогнозом модели. Владелец: Agent A, блок 2."""

from .contracts import Classification, PolicyDecision


def decide(cls: Classification, text: str) -> PolicyDecision:
    """Правила SEC-001 / PRIV-001 / LEG-001 / FIN-001 / LOW-001 / AUTO-001 / DEFAULT."""
    raise NotImplementedError("Agent A, блок 2")


def policy_available() -> bool:
    """Точка инъекции отказа: недоступная policy запрещает любую автоматизацию."""
    return True
