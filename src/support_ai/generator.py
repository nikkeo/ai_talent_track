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
    """Режимы template | llm. При policy.route == ESCALATE LLM не вызывается вообще."""
    return Draft(text=None, citations=[], mode="none", llm_used=False, degraded=True,
                 reason="NOT_IMPLEMENTED")
