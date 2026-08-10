"""Проверка ответа перед отправкой. Владелец: Agent B, блок 2."""

from .contracts import Draft, PolicyDecision, RetrievalResult, Validation


def validate(draft: Draft, retrieval: RetrievalResult, policy: PolicyDecision) -> Validation:
    """Право на автоответ проверяется здесь и только здесь.

    Требуется одновременно: policy.route == AUTO_CANDIDATE, citation на реально
    найденный документ, hit.auto_allowed, approval_status == "published",
    заданный owner, заданный и не истёкший expires_at, отсутствие PII и
    плейсхолдеров в тексте, отсутствие запрещённых обещаний, длина в пределах канала.
    """
    return Validation(ok=False, failed_checks=["not_implemented"])
