"""Маскирование персональных данных до любых внешних вызовов. Владелец: Agent A, блок 1."""

from .contracts import RedactedText


def redact(text: str) -> tuple[RedactedText, dict[str, str]]:
    """Возвращает маскированный текст и карту масок.

    Карта масок никогда не попадает в audit и в LLM.
    """
    raise NotImplementedError("Agent A, блок 1")
