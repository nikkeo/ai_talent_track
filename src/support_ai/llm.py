"""Клиенты LLM и circuit breaker. Владелец: Agent B, блок 2.

По умолчанию сети нет: демо и тесты работают без ключей.
"""

from .contracts import LLM, LLMResult


class MockLLM:
    """Детерминированный генератор поверх переданного контекста.

    Обязан сохранять полученный промпт в last_prompt: на этом построен
    safety-инвариант «исходные PII не уходят в LLM».
    """

    name = "mock"

    def __init__(self) -> None:
        self.last_prompt: str | None = None

    def complete(self, system: str, user: str, timeout_s: float) -> LLMResult:
        raise NotImplementedError("Agent B, блок 2")


class FailingLLM:
    """Всегда таймаут — сценарий S3."""

    name = "fail"

    def complete(self, system: str, user: str, timeout_s: float) -> LLMResult:
        raise TimeoutError("LLM unavailable")


def get_llm(mode: str = "mock") -> LLM:
    """mode: mock | fail | real. real без ключа понижается до mock."""
    return MockLLM() if mode != "fail" else FailingLLM()
