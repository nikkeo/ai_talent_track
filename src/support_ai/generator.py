"""Генерация черновика ответа. Владелец: Agent B, блок 2.

Заглушка ничего не генерирует: pipeline обязан отработать это как деградацию.
"""

from .contracts import Draft, LLM, PolicyDecision, RedactedText, RetrievalResult, Ticket


def make_draft(
    ticket: Ticket,
    redacted: RedactedText,
    retrieval: RetrievalResult,
    policy: PolicyDecision,
    llm: LLM,
) -> Draft:
    """Режимы template | llm. Без контекста и при запрете policy LLM не вызывается."""
    return Draft(text=None, citations=[], mode="none", llm_used=False, degraded=True,
                 reason="NOT_IMPLEMENTED")
