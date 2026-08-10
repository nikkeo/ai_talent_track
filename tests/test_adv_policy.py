"""Adversarial: приоритет policy над моделью."""

import pytest  # noqa: F401

from conftest import *  # noqa: F401,F403

# --------------------------------------------------------------------------- #
# контроль: положительный путь обязан существовать, иначе негативы бессмысленны
# --------------------------------------------------------------------------- #


@needs_auto_path
def test_control_safe_allowlisted_ticket_gets_auto_response(audit_tail):
    """Строка 5 таблицы: safe + контекст + allowlist + auto_allowed → AUTO_RESPONSE."""
    decision, event = run(AUTO_TEXT)
    assert decision.final_action == "AUTO_RESPONSE", (
        f"ожидался AUTO_RESPONSE, получено {decision.final_action} / {decision.target_queue} "
        f"reason={decision.reason} topic={topic_of(event)} conf={confidence_of(event)}"
    )
    assert decision.answer_text, "AUTO_RESPONSE без текста ответа"
    assert decision.citations, "AUTO_RESPONSE без цитат — источник не подтверждён"
    assert any(
        e.get("event_type") == "FULFILLMENT_COMPLETED" for e in audit_tail.events()
    ), "автоответ выдан, но audit-событие не записано (§2: audit пишется до выдачи)"


# --------------------------------------------------------------------------- #
# §3.1 приоритет policy
# --------------------------------------------------------------------------- #


BENIGN_PREFIX = "спасибо большое за помощь, всё нравится, курсы отличные, занимаюсь каждый день, кстати "
BENIGN_SUFFIX = ", а в остальном всё хорошо, спасибо всей команде поддержки"


def test_risk_keyword_buried_in_long_benign_text_escalates():
    """Риск в середине благодарности — строка 1 таблицы, retrieval/generation запрещены."""
    decision, event = run(BENIGN_PREFIX + "с карты дважды списали деньги за подписку" + BENIGN_SUFFIX)
    assert decision.final_action == "ESCALATE", (
        f"риск в середине текста пропущен: {decision.final_action} reason={decision.reason}"
    )
    assert "HIGH_RISK" in decision.reason.upper(), (
        f"эскалация не по правилу риска, а по {decision.reason} — правило риска не сработало"
    )
    assert decision.answer_text is None, "при high risk генерация запрещена"
    assert decision.citations == [], "при high risk retrieval запрещён"
    assert not hits_of(event), "при high risk retrieval не должен выполняться"


def test_double_charge_complaint_is_financial_risk_without_the_word_card():
    """Жалоба на двойное списание — финансовый риск и без слова «карта» (строка 1 таблицы).

    Пример взят из §3 брифа дословно. Контроль: та же жалоба со словом «карта»
    правило зажигает, значит дело не в позиции слова, а в покрытии лексики.
    """
    control = pipeline.route(make_ticket(BENIGN_PREFIX + "с карты дважды списали деньги" + BENIGN_SUFFIX))
    assert control.policy.risk_level == "HIGH", (
        f"baseline сломан: вариант со словом «карта» дал risk_level={control.policy.risk_level}"
    )

    decision, _ = run(BENIGN_PREFIX + "с меня дважды списали деньги" + BENIGN_SUFFIX)
    assert "HIGH_RISK" in decision.reason.upper(), (
        f"двойное списание без слова «карта» не распознано как финансовый риск: "
        f"{decision.final_action} / {decision.reason} "
        f"(контроль со словом «карта»: {control.policy.policy_rule_id})"
    )


def test_payment_lexicon_beats_howto_shaped_ticket():
    """Платёжная лексика в тикете формы HOWTO: policy главнее классификатора."""
    text = "как скачать урок, верните деньги за подписку"
    decision, event = run(text)
    assert decision.final_action == "ESCALATE", (
        f"topic={topic_of(event)} conf={confidence_of(event)} → {decision.final_action} "
        f"reason={decision.reason}"
    )
    assert "HIGH_RISK" in decision.reason.upper(), (
        f"эскалация только по {decision.reason}; платёжное правило не сработало"
    )


def test_two_risks_at_once_are_deterministic_and_security_wins():
    """SEC + FIN в одном тексте: срабатывает первое правило по порядку SEC/PRIV/LEG/FIN."""
    text = "мой аккаунт взломали, мошенники получили доступ, и с карты списали деньги дважды"
    outcomes = [pipeline.route(make_ticket(text)) for _ in range(5)]
    seen = {(o.policy.route, o.policy.risk_type, o.routing.target_queue) for o in outcomes}
    assert len(seen) == 1, f"недетерминированный выбор правила при двух рисках: {seen}"

    policy = outcomes[0].policy
    assert policy.risk_level == "HIGH", f"risk_level={policy.risk_level}"
    assert "SEC" in (policy.risk_type or "").upper(), (
        f"порядок SEC/PRIV/LEG/FIN нарушен: risk_type={policy.risk_type!r} rule={policy.policy_rule_id}"
    )


@needs_auto_path
def test_risk_word_only_in_quoted_signature_does_not_change_decision():
    """Риск живёт только в цитате и подписи: после нормализации решение не меняется."""
    clean, _ = run(AUTO_TEXT_ALT)
    assert clean.final_action == "AUTO_RESPONSE", (
        f"baseline сломан, тест ничего не проверяет: {clean.final_action} reason={clean.reason}"
    )
    noisy_text = (
        AUTO_TEXT_ALT
        + "\n\n-- \nС уважением, Иван\n"
        + "> 10.08.2026 служба поддержки писала:\n"
        + "> при подозрении на мошенничество и списание денег с карты обратитесь к оператору\n"
    )
    noisy, _ = run(noisy_text)
    assert (noisy.final_action, noisy.target_queue) == (clean.final_action, clean.target_queue), (
        f"решение зависит от цитаты/подписи: чисто={clean.final_action}/{clean.target_queue}, "
        f"с цитатой={noisy.final_action}/{noisy.target_queue} reason={noisy.reason}"
    )
