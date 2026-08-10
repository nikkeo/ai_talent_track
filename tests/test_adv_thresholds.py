"""Adversarial: границы порогов и лимитов."""

import pytest  # noqa: F401

from conftest import *  # noqa: F401,F403

# --------------------------------------------------------------------------- #
# §3.2 границы порогов
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text,label",
    [
        ("", "пустой текст"),
        ("     \t\n   ", "одни пробелы"),
        ("!!! ??? ... --- ,,,", "одни знаки препинания"),
        ("кварк зюмба фиолетовый дирижабль", "бессмыслица"),
    ],
)
def test_degenerate_text_escalates(text, label):
    """Строка 2 таблицы: low confidence / UNKNOWN → ESCALATE без retrieval и generation."""
    decision, event = run(text)
    assert decision.final_action == "ESCALATE", (
        f"{label}: topic={topic_of(event)} conf={confidence_of(event)} → "
        f"{decision.final_action} reason={decision.reason}"
    )
    assert decision.answer_text is None, f"{label}: генерация при low confidence запрещена"


def test_ticket_exactly_at_max_chars_is_processed():
    """Ровно MAX_TICKET_CHARS — валидный вход, обрабатывается штатно."""
    text = ((AUTO_TEXT or "как скачать урок") + ". ") * 400
    text = text[: config.MAX_TICKET_CHARS]
    assert len(text) == config.MAX_TICKET_CHARS
    decision, _ = run(text)
    assert decision.final_action in ACTIONS
    assert decision.status in {"COMPLETED", "NEEDS_HUMAN", "FAILED"}


def test_ticket_one_char_over_max_is_handled_deterministically():
    """MAX_TICKET_CHARS + 1 не должен ронять пайплайн и обязан решаться одинаково."""
    text = ((AUTO_TEXT or "как скачать урок") + ". ") * 400
    text = text[: config.MAX_TICKET_CHARS + 1]
    assert len(text) == config.MAX_TICKET_CHARS + 1
    first, _ = run(text)
    second, _ = run(text)
    assert first.final_action in ACTIONS
    assert (first.final_action, first.target_queue) == (second.final_action, second.target_queue)


def test_risk_beyond_max_chars_is_not_silently_dropped():
    """Обрезка по MAX_TICKET_CHARS не должна отменять правило риска (fail-closed, §2).

    Тот же риск в пределах лимита даёт ESCALATE; если вынести его за границу обрезки,
    решение обязано быть не мягче — иначе лимит становится способом обойти policy.
    """
    padding = ((AUTO_TEXT or "как скачать урок") + ". ") * 400
    risk = " ВАЖНО: мой аккаунт взломали мошенники, с карты списали деньги"

    within, _ = run(padding[:2000] + risk)
    assert within.final_action == "ESCALATE", (
        f"baseline сломан: риск в пределах лимита дал {within.final_action} ({within.reason})"
    )

    beyond, _ = run(padding[: config.MAX_TICKET_CHARS] + risk)
    assert SEVERITY[beyond.final_action] >= SEVERITY[within.final_action], (
        f"риск за границей {config.MAX_TICKET_CHARS} символов потерян: "
        f"в пределах лимита {within.final_action}/{within.reason}, "
        f"за лимитом {beyond.final_action}/{beyond.reason}"
    )


def test_confidence_below_threshold_never_automates():
    """Инвариант строки 2 на всём eval-корпусе: conf < CONF_THRESHOLD или UNKNOWN → ESCALATE."""
    rows = [
        json.loads(line)
        for line in config.EVAL_TICKETS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    violations = []
    for row in rows:
        decision, event = run(row["text"])
        conf, topic = confidence_of(event), topic_of(event)
        if conf is None:
            continue
        if (conf < config.CONF_THRESHOLD or topic == "UNKNOWN") and decision.final_action != "ESCALATE":
            violations.append((row["text"][:50], topic, conf, decision.final_action, decision.reason))
    assert not violations, f"низкая уверенность без ESCALATE: {violations}"


def test_relevance_below_threshold_yields_no_reliable_context():
    """Строка 3 таблицы: max_score < RELEVANCE_THRESHOLD → ESCALATE(NO_RELIABLE_CONTEXT)."""
    texts = [
        "как перенести конспект в облако",
        "когда будет завершено плановое обслуживание платформы",
        "как настроить корпоративный прокси для доступа к платформе",
    ]
    checked, violations = 0, []
    for text in texts:
        decision, event = run(text)
        score = max_score_of(event)
        if score is None or score >= config.RELEVANCE_THRESHOLD:
            continue
        checked += 1
        if decision.final_action != "ESCALATE" or "NO_RELIABLE_CONTEXT" not in decision.reason.upper():
            violations.append((text[:40], score, decision.final_action, decision.reason))
    if not checked:
        pytest.skip("не удалось получить тикет с max_score ниже порога релевантности")
    assert not violations, f"нет надёжного контекста, но не ESCALATE/NO_RELIABLE_CONTEXT: {violations}"


def test_confidence_exactly_at_threshold_boundary():
    """Граница CONF_THRESHOLD: ровно порог — это ещё не 'low confidence'."""
    rows = [
        json.loads(line)
        for line in config.EVAL_TICKETS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows += [{"text": t} for t in (AUTO_TEXT, AUTO_TEXT_ALT, "не воспроизводится видео в приложении")]
    for row in rows:
        decision, event = run(row["text"])
        conf = confidence_of(event)
        if conf is not None and abs(conf - config.CONF_THRESHOLD) < 1e-12:
            assert "LOW_CONFIDENCE" not in decision.reason.upper(), (
                f"confidence ровно {conf} == CONF_THRESHOLD трактуется как low: reason={decision.reason}"
            )
            return
    pytest.skip("не найден вход с confidence ровно на пороге — граница не покрыта данными")


def test_relevance_exactly_at_threshold_boundary():
    """Граница RELEVANCE_THRESHOLD: ровно порог — контекст считается найденным."""
    for text in (AUTO_TEXT, AUTO_TEXT_ALT, "нет звука во время урока", "как перенести конспект в облако"):
        decision, event = run(text)
        score = max_score_of(event)
        if score is not None and abs(score - config.RELEVANCE_THRESHOLD) < 1e-12:
            assert "NO_RELIABLE_CONTEXT" not in decision.reason.upper(), (
                f"max_score ровно {score} == RELEVANCE_THRESHOLD трактуется как 'контекст не найден'"
            )
            return
    pytest.skip("не найден вход с max_score ровно на пороге — граница не покрыта данными")
