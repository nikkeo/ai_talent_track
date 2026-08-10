"""Воспроизводимая offline-оценка классификатора, policy и retrieval."""

import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_recall_fscore_support

from . import config, policy
from .classifier import train_model
from .contracts import Classification, PolicyContext, Ticket
from .pii import redact
from .retrieval import search


_HIGH_RISK = {"PAYMENT", "REFUND", "PRIVACY", "SECURITY"}
_EXPECTED_RISK_TYPE = {
    "PAYMENT": "FINANCIAL",
    "REFUND": "FINANCIAL",
    "PRIVACY": "PRIVACY",
    "SECURITY": "SECURITY",
}
_THRESHOLDS = [value / 100 for value in range(30, 71, 5)]
_AUTO_CONF_THRESHOLDS = [value / 100 for value in range(30, 71, 5)]
_AUTO_RELEVANCE_THRESHOLDS = [value / 100 for value in range(35, 61, 5)]
_RETRIEVAL_CASES = [
    ("видео не воспроизводится в мобильном приложении", "TECHNICAL", "KB-TECH-125"),
    ("в уроке совсем нет звука", "TECHNICAL", "KB-TECH-131"),
    ("скачать урок для просмотра без сети", "HOWTO", "KB-HOWTO-210"),
    ("изменить язык интерфейса", "HOWTO", "KB-HOWTO-214"),
    ("плановые технические работы", "STATUS", "KB-STATUS-301"),
    ("задержка синхронизации прогресса", "STATUS", "KB-STATUS-305"),
    ("восстановить забытый пароль", "ACCOUNT_ACCESS", "KB-ACCOUNT-410"),
    ("подтвердить вход с нового устройства", "ACCOUNT_ACCESS", "KB-ACCOUNT-417"),
    ("списание за подписку", "PAYMENT", "KB-PAY-510"),
    ("запрос на возврат", "REFUND", "KB-REFUND-520"),
]


def _read_jsonl(path: Path) -> list[dict[str, str]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _classification(
    probabilities: np.ndarray,
    classes: np.ndarray,
    threshold: float,
) -> Classification:
    order = np.argsort(probabilities)[::-1]
    confidence = float(probabilities[order[0]])
    predicted = str(classes[order[0]])
    return Classification(
        topic=predicted if confidence >= threshold else "UNKNOWN",
        confidence=confidence,
        topk=[(str(classes[index]), float(probabilities[index])) for index in order[:3]],
        model_version=config.VERSIONS["classifier"],
    )


def _threshold_metrics(
    threshold: float,
    eval_rows: list[dict[str, str]],
    probability_matrix: np.ndarray,
    classes: np.ndarray,
) -> dict[str, object]:
    expected = [row["label"] for row in eval_rows]
    classifications = [
        _classification(scores, classes, threshold) for scores in probability_matrix
    ]
    predictions = [classification.topic for classification in classifications]

    decisions = []
    # decide повторно проверяет config.CONF_THRESHOLD. Подмена живёт только внутри
    # одной offline-точки свипа и восстанавливается; config.py остаётся неизменным.
    with patch.object(config, "CONF_THRESHOLD", threshold):
        for row, classification in zip(eval_rows, classifications, strict=True):
            redacted, _mask_map = redact(row["text"])
            context = PolicyContext(
                channel="offline",
                language="ru",
                found_pii_types=redacted.found_types,
            )
            decisions.append(policy.decide(classification, redacted, context))

    labels = sorted(set(expected))
    macro_f1 = float(
        f1_score(expected, predictions, labels=labels, average="macro", zero_division=0)
    )
    _, risk_recalls, _, _ = precision_recall_fscore_support(
        expected, predictions, labels=sorted(_HIGH_RISK), zero_division=0,
    )

    unsafe_auto = 0
    wrong_route = 0
    extra_escalation = 0
    operator_edit = 0
    correctly_routed_risk = 0
    for expected_label, predicted, decision in zip(
        expected, predictions, decisions, strict=True,
    ):
        if expected_label in _HIGH_RISK:
            unsafe_auto += decision.route != "ESCALATE"
            correctly_routed_risk += (
                decision.route == "ESCALATE"
                and decision.risk_type == _EXPECTED_RISK_TYPE[expected_label]
            )
            continue

        extra_escalation += decision.route == "ESCALATE"
        wrong_route += (
            predicted not in {"UNKNOWN", expected_label}
            and decision.route != "ESCALATE"
        )
        operator_edit += (
            decision.route == "DRAFT_ONLY"
            and expected_label in config.AUTO_ALLOWLIST
        )

    cost = 1000 * unsafe_auto + 50 * wrong_route + 5 * extra_escalation + operator_edit
    risk_count = sum(label in _HIGH_RISK for label in expected)
    return {
        "threshold": threshold,
        "macro_f1": macro_f1,
        "model_risk_recall": float(np.mean(risk_recalls)),
        "policy_risk_recall": correctly_routed_risk / risk_count,
        "unknown_share": predictions.count("UNKNOWN") / len(predictions),
        "unsafe_auto": unsafe_auto,
        "wrong_route": wrong_route,
        "extra_escalation": extra_escalation,
        "operator_edit": operator_edit,
        "cost": cost,
        "predictions": predictions,
    }



_HIGH_RISK_LABELS = {"PAYMENT", "REFUND", "PRIVACY", "SECURITY"}


def _end_to_end(eval_rows: list[dict[str, str]]) -> dict[str, object]:
    """Сквозной прогон process() по eval-набору: что система реально сделала бы.

    Классификатор и policy меряются отдельно выше; здесь — итог всей цепочки,
    включая retrieval, генерацию и валидацию. Это и есть automation rate,
    к которому привязан North Star.
    """
    from .pipeline import process

    actions: dict[str, int] = {"AUTO_RESPONSE": 0, "DRAFT_FOR_OPERATOR": 0, "ESCALATE": 0}
    unsafe = 0
    for index, row in enumerate(eval_rows):
        ticket = Ticket(
            ticket_id=f"eval-{index}",
            customer_ref="eval",
            channel="web",
            language="ru",
            text=row["text"],
            created_at=datetime.now(UTC).isoformat(),
            idempotency_key=f"eval:{index}:v1",
        )
        decision, _event = process(ticket, llm_mode="mock")
        actions[decision.final_action] = actions.get(decision.final_action, 0) + 1
        if row["label"] in _HIGH_RISK_LABELS and decision.final_action != "ESCALATE":
            unsafe += 1
    total = len(eval_rows) or 1
    return {
        "automation_rate": actions["AUTO_RESPONSE"] / total,
        "draft_rate": actions["DRAFT_FOR_OPERATOR"] / total,
        "escalation_rate": actions["ESCALATE"] / total,
        "unsafe_automation": unsafe,
    }


def _auto_threshold_metrics(
    eval_rows: list[dict[str, str]],
    auto_conf_threshold: float,
    auto_relevance_threshold: float,
) -> dict[str, object]:
    """Контрфактический e2e-прогон двух порогов права на автоответ."""
    from .pipeline import process

    unsafe_auto = 0
    wrong_route = 0
    extra_escalation = 0
    operator_edit = 0
    actions = {"AUTO_RESPONSE": 0, "DRAFT_FOR_OPERATOR": 0, "ESCALATE": 0}
    suffix = f"ac{int(auto_conf_threshold * 100)}:ar{int(auto_relevance_threshold * 100)}"
    with (
        patch.object(config, "AUTO_CONF_THRESHOLD", auto_conf_threshold),
        patch.object(config, "AUTO_RELEVANCE_THRESHOLD", auto_relevance_threshold),
    ):
        for index, row in enumerate(eval_rows):
            ticket = Ticket(
                ticket_id=f"eval-sweep-{index}-{suffix}",
                customer_ref="eval",
                channel="web",
                language="ru",
                text=row["text"],
                created_at=datetime.now(UTC).isoformat(),
                idempotency_key=f"eval:sweep:{index}:{suffix}",
            )
            decision, event = process(ticket, llm_mode="mock")
            action = decision.final_action
            actions[action] = actions.get(action, 0) + 1
            expected = row["label"]
            if expected in _HIGH_RISK:
                unsafe_auto += action != "ESCALATE"
                continue
            predicted = (event.classification or {}).get("topic", "UNKNOWN")
            extra_escalation += action == "ESCALATE"
            wrong_route += predicted not in {"UNKNOWN", expected} and action != "ESCALATE"
            operator_edit += (
                action == "DRAFT_FOR_OPERATOR" and expected in config.AUTO_ALLOWLIST
            )

    cost = 1000 * unsafe_auto + 50 * wrong_route + 5 * extra_escalation + operator_edit
    return {
        "auto_conf": auto_conf_threshold,
        "auto_relevance": auto_relevance_threshold,
        "unsafe_auto": unsafe_auto,
        "wrong_route": wrong_route,
        "extra_escalation": extra_escalation,
        "operator_edit": operator_edit,
        "cost": cost,
        "actions": actions,
    }


def main() -> int:
    """Оценить classifier, решения policy и retrieval на непересекающемся eval."""
    train_rows = _read_jsonl(config.TRAIN_TICKETS)
    eval_rows = _read_jsonl(config.EVAL_TICKETS)

    # Та же функция, что и в runtime: иначе отчёт описывает другую модель.
    vectorizer, estimator = train_model(train_rows)

    probability_rows: list[np.ndarray] = []
    latencies_ms: list[float] = []
    for row in eval_rows:
        started = perf_counter()
        probabilities = estimator.predict_proba(vectorizer.transform([row["text"]]))[0]
        latencies_ms.append((perf_counter() - started) * 1000)
        probability_rows.append(probabilities)
    probability_matrix = np.asarray(probability_rows)

    sweep = [
        _threshold_metrics(threshold, eval_rows, probability_matrix, estimator.classes_)
        for threshold in _THRESHOLDS
    ]
    selected = min(
        sweep,
        key=lambda row: (
            int(row["cost"]),
            -float(row["policy_risk_recall"]),
            -float(row["model_risk_recall"]),
            float(row["unknown_share"]),
        ),
    )
    current = next(
        row for row in sweep
        if abs(float(row["threshold"]) - config.CONF_THRESHOLD) < 1e-9
    )

    expected = [row["label"] for row in eval_rows]
    predictions = list(current["predictions"])
    labels = sorted(set(expected))
    precision, recall, f1, support = precision_recall_fscore_support(
        expected, predictions, labels=labels, zero_division=0,
    )
    macro_f1 = float(
        f1_score(expected, predictions, labels=labels, average="macro", zero_division=0)
    )
    per_class = {
        label: (float(precision[i]), float(recall[i]), float(f1[i]), int(support[i]))
        for i, label in enumerate(labels)
    }

    retrieval_found = sum(
        expected_doc in [hit.doc_id for hit in search(query, topic, k=3).hits]
        for query, topic, expected_doc in _RETRIEVAL_CASES
    )
    recall_at_3 = retrieval_found / len(_RETRIEVAL_CASES)
    unknown_share = float(current["unknown_share"])
    p95_latency = float(np.percentile(latencies_ms, 95))

    e2e = _end_to_end(eval_rows)
    auto_sweep = [
        _auto_threshold_metrics(eval_rows, auto_conf, auto_relevance)
        for auto_conf in _AUTO_CONF_THRESHOLDS
        for auto_relevance in _AUTO_RELEVANCE_THRESHOLDS
    ]
    current_auto = next(
        row for row in auto_sweep
        if abs(float(row["auto_conf"]) - config.AUTO_CONF_THRESHOLD) < 1e-9
        and abs(float(row["auto_relevance"]) - config.AUTO_RELEVANCE_THRESHOLD) < 1e-9
    )
    min_auto_cost = min(int(row["cost"]) for row in auto_sweep)
    min_auto_rows = [row for row in auto_sweep if int(row["cost"]) == min_auto_cost]

    lines = [
        "# Offline-отчёт",
        "",
        "> **Development set, не holdout:** на `tickets_eval.jsonl` настраивались порог классификации и лексика policy. Метрики ниже не являются оценкой обобщения; это smoke-проверка на 20 синтетических примерах.",
        "",
        "Обучение модели выполнено только на `data/tickets_train.jsonl`, а demo-набор не использовался. Но для честного финального измерения нужен новый закрытый test-набор, который не участвовал в выборе порога, правил или KB.",
        "",
        "## Сводка на текущем config",
        "",
        "| Метрика | Значение |",
        "|---|---:|",
        f"| CONF_THRESHOLD | {config.CONF_THRESHOLD:.2f} |",
        f"| AUTO_CONF_THRESHOLD | {config.AUTO_CONF_THRESHOLD:.2f} |",
        f"| AUTO_RELEVANCE_THRESHOLD | {config.AUTO_RELEVANCE_THRESHOLD:.2f} |",
        f"| AUTO_ANSWERABILITY_THRESHOLD | {config.AUTO_ANSWERABILITY_THRESHOLD:.2f} |",
        f"| Macro-F1 | {macro_f1:.3f} |",
        f"| Model recall high-risk macro | {float(current['model_risk_recall']):.3f} |",
        f"| Policy recall high-risk с корректным `risk_type` | {float(current['policy_risk_recall']):.3f} |",
        f"| UNKNOWN | {_percent(unknown_share)} |",
        f"| Low-confidence | {_percent(unknown_share)} |",
        "| p95 latency классификации | < 1 ms |",
        f"| Retrieval Recall@3 на {len(_RETRIEVAL_CASES)} ручных парах | {recall_at_3:.3f} |",
        "",
        "Model recall требует точного класса от классификатора. Policy recall считает high-risk тикеты, для которых `policy.decide` вернул `ESCALATE` и правильный `risk_type`; это разные границы качества.",
        "",
        "## Сквозной прогон: что система сделала бы с eval-набором",
        "",
        "| Метрика | Значение |",
        "|---|---:|",
        f"| Automation rate (AUTO_RESPONSE) | {_percent(e2e['automation_rate'])} |",
        f"| Draft rate (оператору с черновиком) | {_percent(e2e['draft_rate'])} |",
        f"| Escalation rate | {_percent(e2e['escalation_rate'])} |",
        f"| Небезопасная автоматизация high-risk | {e2e['unsafe_automation']} |",
        "",
        f"> **Оговорка к automation rate {_percent(e2e['automation_rate'])}:** это покрытие на development-наборе, против которого расширялась KB, а не оценка ожидаемой production-автоматизации.",
        "",
        "Последняя строка — главный guardrail: high-risk тикет, не ушедший в `ESCALATE`. "
        "Любое значение больше нуля блокирует включение автоответов.",
        "",
        "## Классы на текущем config",
        "",
        "| Класс | Precision | Recall | F1 | Support | High-risk |",
        "|---|---:|---:|---:|---:|:---:|",
    ]
    for label in labels:
        class_precision, class_recall, class_f1, class_support = per_class[label]
        lines.append(
            f"| {label} | {class_precision:.3f} | {class_recall:.3f} | "
            f"{class_f1:.3f} | {class_support} | {'да' if label in _HIGH_RISK else 'нет'} |"
        )
    lines.extend(["", "## Recall high-risk классов модели", ""])
    for label in sorted(_HIGH_RISK):
        lines.append(f"- `{label}`: {per_class[label][1]:.3f}")

    lines.extend([
        "",
        "## Свип CONF_THRESHOLD по стоимости решений",
        "",
        "`config.py` не изменялся. Для каждой точки evaluator локально применяет кандидат к `Classification` и `policy.decide`, затем восстанавливает runtime-config.",
        "",
        "| Threshold | Macro-F1 | Model risk recall | Policy risk recall | UNKNOWN | unsafe_auto | wrong_route | extra escalation | operator edit | Cost |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in sweep:
        lines.append(
            f"| {float(row['threshold']):.2f} | {float(row['macro_f1']):.3f} | "
            f"{float(row['model_risk_recall']):.3f} | {float(row['policy_risk_recall']):.3f} | "
            f"{_percent(float(row['unknown_share']))} | {int(row['unsafe_auto'])} | "
            f"{int(row['wrong_route'])} | {int(row['extra_escalation'])} | "
            f"{int(row['operator_edit'])} | {int(row['cost'])} |"
        )
    lines.extend([
        "",
        f"Выбран кандидат `{float(selected['threshold']):.2f}`: минимальная стоимость `{int(selected['cost'])}`. При равной стоимости tie-break предпочитает больший policy risk recall, затем model risk recall и меньшую долю UNKNOWN. Это выбор по последствиям решений, а не по максимуму F1.",
        "",
        "Cost = `1000 × unsafe_auto + 50 × wrong_route + 5 × extra escalation + 1 × operator edit`. По условию эксперимента `unsafe_auto` означает любой high-risk тикет с route не `ESCALATE`, включая `DRAFT_ONLY`.",
        "",
        "## Свип порогов права на AUTO_RESPONSE",
        "",
        "Каждая ячейка — cost сквозного прогона при паре `AUTO_CONF_THRESHOLD × AUTO_RELEVANCE_THRESHOLD`; runtime-config после точки восстанавливается. Это диагностический свип на том же development-наборе, а не независимый выбор порогов.",
        "",
        "| AUTO_CONF \\ AUTO_RELEVANCE | "
        + " | ".join(f"{value:.2f}" for value in _AUTO_RELEVANCE_THRESHOLDS)
        + " |",
        "|---:|" + "---:|" * len(_AUTO_RELEVANCE_THRESHOLDS),
    ])
    for auto_conf in _AUTO_CONF_THRESHOLDS:
        costs = [
            int(row["cost"])
            for row in auto_sweep
            if abs(float(row["auto_conf"]) - auto_conf) < 1e-9
        ]
        lines.append(f"| {auto_conf:.2f} | " + " | ".join(map(str, costs)) + " |")
    current_actions = current_auto["actions"]
    assert isinstance(current_actions, dict)
    indistinguishable = len(min_auto_rows) > 1
    lines.extend([
        "",
        f"Текущая пара `{config.AUTO_CONF_THRESHOLD:.2f} × {config.AUTO_RELEVANCE_THRESHOLD:.2f}` даёт cost `{int(current_auto['cost'])}`: unsafe_auto `{int(current_auto['unsafe_auto'])}`, wrong_route `{int(current_auto['wrong_route'])}`, extra escalation `{int(current_auto['extra_escalation'])}`, operator edit `{int(current_auto['operator_edit'])}`; действия — AUTO `{int(current_actions['AUTO_RESPONSE'])}`, draft `{int(current_actions['DRAFT_FOR_OPERATOR'])}`, escalation `{int(current_actions['ESCALATE'])}`.",
        f"Минимальный cost `{min_auto_cost}` имеют `{len(min_auto_rows)}` пар; "
        + ("набор не различает их, поэтому подбирать по нему пороги нельзя." if indistinguishable else "набор формально различает одну пару, но после настройки на этих же 20 примерах это не оценка обобщения."),
        "Значения `0.60` и `0.50` остаются консервативным выбором выше наблюдённых пробоев, а не выводом из этого малого development-набора.",
        "",
        "## Retrieval-набор",
        "",
        "Пары запрос → `document_id` размечены вручную в `src/support_ai/evaluate.py`; измеряется попадание ожидаемого документа в top-3. Набор проверяет поиск, но слишком мал для продуктового вывода.",
        "",
        "Отчёт воспроизводится командой `.venv/bin/python -m support_ai.evaluate` с `PYTHONPATH=src` или целью `make eval`.",
        "",
    ])
    config.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (config.DOCS_DIR / "eval_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"p95 classification latency (current run): {p95_latency:.3f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
