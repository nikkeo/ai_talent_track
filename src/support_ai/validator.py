"""Проверка ответа перед отправкой. Владелец: Agent B, блок 2."""

from .contracts import Draft, PolicyDecision, RetrievalResult, Validation


def validate(draft: Draft, retrieval: RetrievalResult, policy: PolicyDecision) -> Validation:
    """Право на автоответ проверяется здесь и только здесь.

    Требуется одновременно: policy.route == AUTO_CANDIDATE, citation на реально
    найденный документ, hit.auto_allowed, approval_status == "published",
    заданный owner, заданный и не истёкший expires_at, отсутствие PII и
    плейсхолдеров в тексте, отсутствие запрещённых обещаний, длина не выше
    config.MAX_ANSWER_CHARS.

    Лимит длины единый для всех каналов: channel сюда не передаётся, обещать
    per-channel проверку было бы невыполнимо. Разные лимиты по каналам —
    вопрос целевой архитектуры, не PoC.
    """
    return Validation(ok=False, failed_checks=["not_implemented"])
