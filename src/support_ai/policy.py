"""Детерминированная бизнес-policy. Приоритет над прогнозом модели. Владелец: Agent A, блок 2."""

from . import config
from .contracts import Classification, PolicyContext, PolicyDecision, RedactedText


def _decision(
    route: str,
    risk_level: str,
    risk_type: str | None,
    target_queue: str,
    rule: str,
    reason: str,
) -> PolicyDecision:
    return PolicyDecision(
        route=route,  # type: ignore[arg-type]
        risk_level=risk_level,  # type: ignore[arg-type]
        risk_type=risk_type,
        target_queue=target_queue,
        policy_rule_id=rule,
        policy_version=config.VERSIONS["policy"],
        reason=reason,
    )


def decide(
    classification: Classification,
    redacted: RedactedText,
    context: PolicyContext,
) -> PolicyDecision:
    """Правила SEC-001 / PRIV-001 / LEG-001 / FIN-001 / LOW-001 / AUTO-001 / DEFAULT.

    Принимает именно RedactedText: неверный вызов с сырым текстом виден по типу.
    Возвращает ровно один route: ESCALATE | DRAFT_ONLY | AUTO_CANDIDATE.
    """
    if not policy_available():
        return _decision("ESCALATE", "HIGH", None, "general", "POLICY-FAIL", "POLICY_UNAVAILABLE")

    text = redacted.text.casefold()
    rules = (
        ("SEC-001", ("взлом", "украли аккаунт", "украли доступ", "мошенник", "фишинг",
                     "неизвестный вход", "неизвестная сессия", "неизвестное устройство",
                     "неизвестного устройства", "учетных данных", "учётных данных",
                     "подозрительный вход", "вход в профиль",
                     "чужое устройство", "чужого устройства"), "SECURITY", "security"),
        ("PRIV-001", ("удалить мои данные", "удалите мои", "утечк", "персональн",
                      "запрещаю хранить", "хранить информацию", "выгрузк", "обо мне",
                      "о пользователе", "gdpr"), "PRIVACY", "privacy"),
        ("LEG-001", ("суд", "претензи", "жалоб", "надзор", "нарушение договора"), "LEGAL", "legal"),
    )
    for rule, keywords, risk_type, queue in rules:
        if any(keyword in text for keyword in keywords):
            return _decision("ESCALATE", "HIGH", risk_type, queue, rule, f"HIGH_RISK_{risk_type}")

    financial = (
        classification.topic in {"PAYMENT", "REFUND"}
        or "CARD" in context.found_pii_types
        or any(word in text for word in ("списа", "возврат", "верните деньги", "вернуть деньги", "chargeback", "двойн"))
    )
    if financial:
        return _decision(
            "ESCALATE", "HIGH", "FINANCIAL", "financial-support", "FIN-001", "HIGH_RISK_FINANCIAL"
        )
    if classification.topic == "UNKNOWN" or classification.confidence < config.CONF_THRESHOLD:
        return _decision("ESCALATE", "MEDIUM", None, "general", "LOW-001", "LOW_CONFIDENCE")
    if classification.topic in config.AUTO_ALLOWLIST:
        return _decision("AUTO_CANDIDATE", "LOW", None, "automation", "AUTO-001", "AUTO_ALLOWED_TOPIC")
    return _decision("DRAFT_ONLY", "MEDIUM", None, "general", "DEFAULT", "HUMAN_REVIEW_REQUIRED")


def policy_available() -> bool:
    """Точка инъекции отказа: недоступная policy запрещает любую автоматизацию."""
    return True
