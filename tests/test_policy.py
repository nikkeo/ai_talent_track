import pytest

from support_ai.contracts import Classification, PolicyContext, RedactedText
from support_ai.policy import decide


def classification(topic: str, confidence: float) -> Classification:
    return Classification(topic, confidence, [(topic, confidence)], "test")


def context(*pii: str) -> PolicyContext:
    return PolicyContext(channel="chat", language="ru", found_pii_types=list(pii))


def test_security_rule_has_priority_over_safe_classification() -> None:
    result = decide(
        classification("HOWTO", 0.99),
        RedactedText("мошенники украли аккаунт", []),
        context(),
    )

    assert result.route == "ESCALATE"
    assert result.policy_rule_id == "SEC-001"
    assert result.target_queue == "security"


@pytest.mark.parametrize(
    ("text", "rule", "queue"),
    [
        ("произошла утечка персональных данных", "PRIV-001", "privacy"),
        ("подам жалобу в надзор и обращусь в суд", "LEG-001", "legal"),
    ],
)
def test_high_risk_keywords_override_safe_topic(text: str, rule: str, queue: str) -> None:
    result = decide(classification("HOWTO", 0.99), RedactedText(text, []), context())

    assert result.route == "ESCALATE"
    assert result.policy_rule_id == rule
    assert result.target_queue == queue


def test_first_high_risk_rule_wins() -> None:
    result = decide(
        classification("REFUND", 0.99),
        RedactedText("мошенники требуют возврат, подам в суд", []),
        context(),
    )

    assert result.policy_rule_id == "SEC-001"


def test_payment_is_never_automatic_despite_confidence() -> None:
    result = decide(classification("PAYMENT", 0.97), RedactedText("вопрос об оплате", []), context())

    assert result.route == "ESCALATE"
    assert result.policy_rule_id == "FIN-001"
    assert result.target_queue == "financial-support"


def test_low_confidence_goes_to_general_queue() -> None:
    result = decide(classification("UNKNOWN", 0.2), RedactedText("новый вопрос", []), context())

    assert result.route == "ESCALATE"
    assert result.reason == "LOW_CONFIDENCE"
    assert result.target_queue == "general"


def test_allowlisted_topic_becomes_auto_candidate() -> None:
    result = decide(classification("TECHNICAL", 0.9), RedactedText("не работает видео", []), context())

    assert result.route == "AUTO_CANDIDATE"
    assert result.policy_rule_id == "AUTO-001"


def test_card_signal_forbids_automation() -> None:
    result = decide(classification("HOWTO", 0.9), RedactedText("как сменить карту <CARD_1>", ["CARD"]), context("CARD"))

    assert result.route == "ESCALATE"
    assert result.policy_rule_id == "FIN-001"


def test_unavailable_policy_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr("support_ai.policy.policy_available", lambda: False)

    result = decide(classification("TECHNICAL", 0.99), RedactedText("не работает видео", []), context())

    assert result.route == "ESCALATE"
    assert result.reason == "POLICY_UNAVAILABLE"
