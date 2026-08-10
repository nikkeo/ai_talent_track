"""Детерминированные локальные LLM-адаптеры без сети и ключей."""

import re
from time import perf_counter

from .contracts import LLM, LLMResult


class MockLLM:
    """Детерминированный генератор поверх переданного контекста.

    Обязан сохранять полученный промпт в last_prompt: на этом построен
    safety-инвариант «исходные PII не уходят в LLM».
    """

    name = "mock"

    def __init__(self) -> None:
        self.last_prompt: str | None = None
        self.last_result: LLMResult | None = None

    def complete(self, system: str, user: str, timeout_s: float) -> LLMResult:
        started = perf_counter()
        self.last_prompt = f"{system}\n\n{user}"
        match = re.search(r"<context>\s*(.*?)\s*</context>", user, re.DOTALL)
        context = match.group(1).strip() if match else ""
        if context:
            text = f"По инструкции из базы знаний: {context}"
        else:
            text = "В базе знаний недостаточно информации. Обращение должен уточнить оператор."
        self.last_result = LLMResult(
            text=text,
            provider="local",
            model="deterministic-mock-v1",
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=(perf_counter() - started) * 1000,
            request_id=None,
        )
        return self.last_result


class FailingLLM:
    """Всегда таймаут — сценарий S3."""

    name = "fail"

    def complete(self, system: str, user: str, timeout_s: float) -> LLMResult:
        raise TimeoutError("LLM unavailable")


def get_llm(mode: str = "mock") -> LLM:
    """Вернуть один из двух офлайн-адаптеров; неизвестный режим закрывается ошибкой."""
    if mode == "mock":
        return MockLLM()
    if mode == "fail":
        return FailingLLM()
    raise ValueError(f"Unsupported LLM mode: {mode}")
