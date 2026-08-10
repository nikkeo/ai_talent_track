import json

import pytest

from support_ai import config
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


@pytest.mark.parametrize("confidence", [config.CONF_THRESHOLD, 0.59])
def test_known_allowlisted_topic_below_auto_threshold_is_draft_only(confidence: float) -> None:
    result = decide(
        classification("HOWTO", confidence),
        RedactedText("как скачать урок", []),
        context(),
    )

    assert result.route == "DRAFT_ONLY"
    assert result.policy_rule_id == "AUTO-CONF-001"
    assert result.reason == "AUTO_CONFIDENCE_TOO_LOW"


def test_auto_threshold_itself_allows_auto_candidate() -> None:
    result = decide(
        classification("HOWTO", config.AUTO_CONF_THRESHOLD),
        RedactedText("как скачать урок", []),
        context(),
    )

    assert result.route == "AUTO_CANDIDATE"
    assert result.policy_rule_id == "AUTO-001"


def test_duplicate_operations_in_bank_history_trigger_financial_rule() -> None:
    result = decide(
        classification("HOWTO", 0.99),
        RedactedText(
            "за один курс в банковской истории теперь две одинаковые операции, как скачать урок",
            [],
        ),
        context(),
    )

    assert result.route == "ESCALATE"
    assert result.policy_rule_id == "FIN-001"
    assert result.risk_type == "FINANCIAL"


def test_card_signal_forbids_automation() -> None:
    result = decide(classification("HOWTO", 0.9), RedactedText("как сменить карту <CARD_1>", ["CARD"]), context("CARD"))

    assert result.route == "ESCALATE"
    assert result.policy_rule_id == "FIN-001"


def test_unavailable_policy_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr("support_ai.policy.policy_available", lambda: False)

    result = decide(classification("TECHNICAL", 0.99), RedactedText("не работает видео", []), context())

    assert result.route == "ESCALATE"
    assert result.reason == "POLICY_UNAVAILABLE"


@pytest.mark.parametrize(
    "text",
    [
        "урок открывается с неизвестной системной ошибкой",
        "помогите выполнить вход в профиль",
        "как изменить учетные данные",
        "как выгрузить домашнее задание",
        "где находятся персональные настройки",
        "хочу обсудить ошибку воспроизведения",
        "хочу оставить жалобу на зависание приложения",
        "как включить двойную скорость воспроизведения",
        "как выполнить две одинаковые операции в редакторе",
        "возврат на предыдущий экран не работает",
    ],
)
def test_broad_safe_vocabulary_does_not_trigger_high_risk_rule(text: str) -> None:
    result = decide(classification("HOWTO", 0.99), RedactedText(text, []), context())

    assert result.policy_rule_id not in {"SEC-001", "PRIV-001", "LEG-001", "FIN-001"}


def test_no_safe_training_ticket_triggers_high_risk_rule() -> None:
    safe_labels = {"ACCOUNT_ACCESS", "HOWTO", "STATUS", "TECHNICAL"}
    rows = [
        json.loads(line)
        for line in config.TRAIN_TICKETS.read_text(encoding="utf-8").splitlines()
        if line
    ]

    false_positives = []
    for row in rows:
        if row["label"] not in safe_labels:
            continue
        result = decide(
            classification(row["label"], 0.99),
            RedactedText(row["text"], []),
            context(),
        )
        if result.policy_rule_id in {"SEC-001", "PRIV-001", "LEG-001", "FIN-001"}:
            false_positives.append((row["text"], result.policy_rule_id))

    assert false_positives == []


def test_risky_training_tickets_are_caught_even_with_safe_model_topic() -> None:
    expected_rules = {
        "PAYMENT": "FIN-001",
        "REFUND": "FIN-001",
        "PRIVACY": "PRIV-001",
        "SECURITY": "SEC-001",
    }
    rows = [
        json.loads(line)
        for line in config.TRAIN_TICKETS.read_text(encoding="utf-8").splitlines()
        if line
    ]

    missed = []
    for row in rows:
        if row["label"] not in expected_rules:
            continue
        result = decide(
            classification("HOWTO", 0.99),
            RedactedText(row["text"], []),
            context(),
        )
        if result.policy_rule_id != expected_rules[row["label"]]:
            missed.append((row["text"], result.policy_rule_id))

    assert missed == []


def test_train_and_eval_have_no_exact_duplicates() -> None:
    def texts(path) -> set[str]:
        return {
            json.loads(line)["text"].casefold().strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        }

    train_texts = texts(config.TRAIN_TICKETS)
    eval_texts = texts(config.EVAL_TICKETS)

    assert train_texts.isdisjoint(eval_texts)
