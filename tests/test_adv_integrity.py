"""Adversarial: идемпотентность и деградация."""

import pytest  # noqa: F401

from conftest import *  # noqa: F401,F403

# --------------------------------------------------------------------------- #
# §3.5 идемпотентность
# --------------------------------------------------------------------------- #


@needs_auto_path
def test_same_key_different_text_does_not_create_second_decision(audit_tail):
    key = f"adv:idem:{uuid.uuid4().hex}"
    first, _ = run(AUTO_TEXT, key=key)
    assert first.final_action == "AUTO_RESPONSE", f"baseline сломан: {first.final_action}/{first.reason}"

    second, _ = run("мой аккаунт взломали, мошенники сняли деньги", key=key)
    assert (second.final_action, second.target_queue, second.answer_text) == (
        first.final_action,
        first.target_queue,
        first.answer_text,
    ), (
        f"тот же idempotency_key дал новое решение: {first.final_action}/{first.target_queue} "
        f"→ {second.final_action}/{second.target_queue}"
    )
    routed = [
        e
        for e in audit_tail.events()
        if e.get("idempotency_key") == key and e.get("event_type") == "ROUTING_DECIDED"
    ]
    assert len(routed) <= 1, f"на один ключ записано {len(routed)} решений о маршрутизации"


@needs_auto_path
def test_different_keys_same_text_are_independent(audit_tail):
    key_a = f"adv:idem-a:{uuid.uuid4().hex}"
    key_b = f"adv:idem-b:{uuid.uuid4().hex}"
    first, event_a = run(AUTO_TEXT, key=key_a)
    second, event_b = run(AUTO_TEXT, key=key_b)

    assert first.final_action == second.final_action, "одинаковый текст дал разные действия"
    assert event_a.correlation_id != event_b.correlation_id, (
        "разные ключи получили один correlation_id — обращения не независимы"
    )
    keys = {e.get("idempotency_key") for e in audit_tail.events()}
    assert {key_a, key_b} <= keys, f"в аудите нет обоих обращений: {keys}"


@needs_auto_path
def test_retry_after_llm_fault_does_not_double_fulfill(audit_tail):
    key = f"adv:retry:{uuid.uuid4().hex}"
    degraded, _ = run(AUTO_TEXT, key=key, faults={"llm"})
    retried, _ = run(AUTO_TEXT, key=key)
    again, _ = run(AUTO_TEXT, key=key)

    assert (retried.final_action, retried.target_queue) == (again.final_action, again.target_queue), (
        "повторные вызовы с одним ключом недетерминированы"
    )
    auto_events = [
        e
        for e in audit_tail.events()
        if e.get("idempotency_key") == key
        and e.get("event_type") == "FULFILLMENT_COMPLETED"
        and "AUTO_RESPONSE" in json.dumps(e.get("fulfillment_decision") or {}, ensure_ascii=False)
    ]
    assert len(auto_events) <= 1, (
        f"один ключ дал {len(auto_events)} завершённых автоответов "
        f"(первый вызов degraded={degraded.final_action})"
    )


# --------------------------------------------------------------------------- #
# §3.6 деградация
# --------------------------------------------------------------------------- #


@needs_auto_path
def test_audit_fault_forces_escalate():
    """Строка 7 таблицы: audit failed → ESCALATE. Audit пишется до выдачи автоответа."""
    baseline, _ = run(AUTO_TEXT)
    assert baseline.final_action == "AUTO_RESPONSE", f"baseline сломан: {baseline.reason}"

    decision, _ = run(AUTO_TEXT, faults={"audit"})
    assert decision.final_action == "ESCALATE", (
        f"аудит не записан, но выдано {decision.final_action}: reason={decision.reason}"
    )
    assert decision.answer_text is None, "при недоступном аудите ответ клиенту выдаваться не должен"


@needs_auto_path
def test_two_simultaneous_faults_take_the_most_conservative_outcome():
    """faults={'llm','audit'} — результат самый консервативный из двух, а не случайный."""
    llm_only, _ = run(AUTO_TEXT, key=f"adv:f1:{uuid.uuid4().hex}", faults={"llm"})
    audit_only, _ = run(AUTO_TEXT, key=f"adv:f2:{uuid.uuid4().hex}", faults={"audit"})
    both, _ = run(AUTO_TEXT, key=f"adv:f3:{uuid.uuid4().hex}", faults={"llm", "audit"})

    expected = max(SEVERITY[llm_only.final_action], SEVERITY[audit_only.final_action])
    assert SEVERITY[both.final_action] == expected, (
        f"llm={llm_only.final_action}, audit={audit_only.final_action}, "
        f"оба={both.final_action} reason={both.reason}"
    )
    assert both.final_action == "ESCALATE", "audit failed обязан давать ESCALATE"


@needs_auto_path
def test_policy_fault_forbids_automation():
    """faults={'policy'} на заведомо безопасном тикете — автоматизация запрещена."""
    baseline, _ = run(AUTO_TEXT)
    assert baseline.final_action == "AUTO_RESPONSE", f"baseline сломан: {baseline.reason}"

    decision, _ = run(AUTO_TEXT, faults={"policy"})
    assert decision.final_action != "AUTO_RESPONSE", (
        f"policy недоступен, но выдан автоответ: reason={decision.reason}"
    )
