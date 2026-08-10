"""Детерминированная бизнес-policy. Приоритет над прогнозом модели. Владелец: Agent A, блок 2."""

import re

from . import config
from .contracts import Classification, PolicyContext, PolicyDecision, RedactedText


def _compile(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p) for p in patterns)


_HIGH_RISK_PATTERNS = (
    (
        "SEC-001",
        _compile((
            r"\bмошенник\w*\b",
            r"\bфишинг\w*\b",
            r"\b(?:аккаунт|профил\w*|уч[её]тн\w+\s+запис\w*)\b.{0,40}\bвзлом\w*\b",
            r"\bвзлом\w*\b.{0,40}\b(?:аккаунт|профил\w*|уч[её]тн\w+\s+запис\w*)\b",
            r"\bукра(?:ли|ден\w*)\b.{0,40}\b(?:аккаунт|доступ|парол\w*|уч[её]тн\w+\s+данн\w*)\b",
            r"\b(?:аккаунт|доступ|парол\w*|уч[её]тн\w+\s+данн\w*)\b.{0,40}\bукраден\w*\b",
            r"\bкраж\w*\b.{0,40}\b(?:парол\w*|доступ\w*|уч[её]тн\w+\s+данн\w*)\b",
            r"\b(?:неизвестн\w*|подозрительн\w*)\s+(?:вход|сесси\w*|устройств\w*)\b",
            r"\bчуж\w+\s+устройств\w*\b",
            r"\bкто-то\s+вош[её]л\b.{0,40}\b(?:аккаунт|профил\w*)\b",
            r"\bвход\b.{0,50}\b(?:не\s+совершал\w*|без\s+(?:моего\s+)?разрешения)\b",
            r"\b(?:передать|сообщить)\s+пароль\b",
            r"\bбез\s+разрешения\b.{0,40}\b(?:сменил\w*|изменил\w*|вош[её]л)\b",
        )),
        "SECURITY",
        "security",
    ),
    (
        "PRIV-001",
        _compile((
            r"\b(?:удалить|удалите|удали|стереть)\b.{0,50}\b(?:мо[иёйх]*\s+)?(?:персональн\w+\s+)?(?:данн\w*|сведен\w*|информац\w*)\b",
            r"\bутечк\w*\b.{0,40}\b(?:данн\w*|информац\w*|сведен\w*)\b",
            r"\b(?:данн\w*|информац\w*|сведен\w*)\b.{0,40}\bутечк\w*\b",
            r"\b(?:запрещаю|отзываю)\b.{0,60}\b(?:хранить|обработ\w*|использова\w*|согласи\w*|разрешени\w*)\b",
            r"\b(?:выгруз\w*|предоставить)\b.{0,50}\b(?:все\s+|копи\w*\s+)?(?:мо[иёйх]*\s+)?(?:персональн\w+\s+)?(?:данн\w*|сведен\w*)\b",
            r"\bкакие\s+данн\w*\b.{0,50}\bхранит\w*\b.{0,30}\bобо\s+мне\b",
            r"\bgdpr\b",
        )),
        "PRIVACY",
        "privacy",
    ),
    (
        "LEG-001",
        _compile((
            r"\b(?:подам|направлю|обращусь|пойду)\b.{0,40}\b(?:жалоб\w*|претензи\w*|суд)\b",
            r"\b(?:жалоб\w*|претензи\w*)\b.{0,40}\b(?:суд|надзор\w*|прокуратур\w*)\b",
            r"\b(?:суд|надзор\w*|прокуратур\w*)\b.{0,40}\b(?:жалоб\w*|претензи\w*)\b",
            r"\bнарушени\w*\s+договора\b",
        )),
        "LEGAL",
        "legal",
    ),
)

_FINANCIAL_PATTERNS = _compile((
    r"\bсписан(?:ие|ия|ию|ием|ии|ий|о|а|ы|ную|ного|ли)?\b",
    r"\b(?:карт\w*|баланс\w*|сч[её]т\w*|деньги|сумм\w*|оплат\w*)\b.{0,35}\b(?:списал\w*|снял\w*)\b",
    r"\b(?:списал\w*|снял\w*)\b.{0,35}\b(?:карт\w*|баланс\w*|сч[её]т\w*|деньги|сумм\w*|оплат\w*|подписк\w*)\b",
    r"\b(?:верните|вернуть)\b.{0,30}\b(?:деньги|оплат\w*|плат[её]ж\w*|стоимост\w*)\b",
    r"\b(?:возврат\w*|возмещен\w*|компенсац\w*)\b.{0,35}\b(?:денег|денеж\w*|средств|оплат\w*|плат[её]ж\w*|стоимост\w*|карт\w*)\b",
    r"\b(?:деньги|денеж\w*|средств\w*|оплат\w*|плат[её]ж\w*|стоимост\w*)\b.{0,35}\b(?:возврат\w*|возмещен\w*|компенсац\w*)\b",
    r"\b(?:возмещен\w*|компенсац\w*)\b",
    r"\b(?:двойн\w*|дважды|повторн\w*)\b.{0,25}\b(?:списа\w*|оплат\w*|плат[её]ж\w*)\b",
    r"\b(?:оплат\w*|плат[её]ж\w*)\b.{0,30}\b(?:продублиров\w*|отклон\w*|не\s+проходит|ошибк\w*|неверн\w+\s+сумм\w*)\b",
    r"\b(?:банк|ошибк\w*|не\s+могу)\b.{0,30}\b(?:оплат\w*|заплатить)\b",
    r"\bденьги\b.{0,40}\bотмен\w*\b.{0,40}\bне\s+зачислен\w*\b",
    r"\bchargeback\b",
))


def _matches_any(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


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
    for rule, patterns, risk_type, queue in _HIGH_RISK_PATTERNS:
        if _matches_any(text, patterns):
            return _decision("ESCALATE", "HIGH", risk_type, queue, rule, f"HIGH_RISK_{risk_type}")

    financial = (
        classification.topic in {"PAYMENT", "REFUND"}
        or "CARD" in context.found_pii_types
        or _matches_any(text, _FINANCIAL_PATTERNS)
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
