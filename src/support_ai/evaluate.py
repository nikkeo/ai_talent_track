"""Воспроизводимая offline-оценка классификатора и retrieval."""

import json
from pathlib import Path
from time import perf_counter

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_recall_fscore_support

from . import config
from .retrieval import search


_HIGH_RISK = {"PAYMENT", "REFUND", "PRIVACY", "SECURITY"}
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


def main() -> int:
    """macro-F1, per-class recall, recall high-risk, доля UNKNOWN, p95 latency, Recall@3."""
    train_rows = _read_jsonl(config.TRAIN_TICKETS)
    eval_rows = _read_jsonl(config.EVAL_TICKETS)

    vectorizer = TfidfVectorizer(ngram_range=(1, 2), lowercase=True)
    train_features = vectorizer.fit_transform(row["text"] for row in train_rows)
    estimator = LogisticRegression(C=10.0, max_iter=1_000, random_state=0)
    estimator.fit(train_features, [row["label"] for row in train_rows])

    predictions: list[str] = []
    confidences: list[float] = []
    latencies_ms: list[float] = []
    for row in eval_rows:
        started = perf_counter()
        probabilities = estimator.predict_proba(vectorizer.transform([row["text"]]))[0]
        best_index = int(np.argmax(probabilities))
        confidence = float(probabilities[best_index])
        predicted = str(estimator.classes_[best_index])
        if confidence < config.CONF_THRESHOLD:
            predicted = "UNKNOWN"
        latencies_ms.append((perf_counter() - started) * 1000)
        predictions.append(predicted)
        confidences.append(confidence)

    expected = [row["label"] for row in eval_rows]
    labels = sorted(set(expected))
    precision, recall, f1, support = precision_recall_fscore_support(
        expected, predictions, labels=labels, zero_division=0,
    )
    macro_f1 = float(f1_score(expected, predictions, labels=labels, average="macro", zero_division=0))
    per_class = {
        label: (float(precision[i]), float(recall[i]), float(f1[i]), int(support[i]))
        for i, label in enumerate(labels)
    }

    retrieval_found = sum(
        expected_doc in [hit.doc_id for hit in search(query, topic, k=3).hits]
        for query, topic, expected_doc in _RETRIEVAL_CASES
    )
    recall_at_3 = retrieval_found / len(_RETRIEVAL_CASES)
    unknown_share = predictions.count("UNKNOWN") / len(predictions)
    low_confidence_share = sum(score < config.CONF_THRESHOLD for score in confidences) / len(confidences)
    p95_latency = float(np.percentile(latencies_ms, 95))

    lines = [
        "# Offline-отчёт",
        "",
        "> **Ограничение:** eval-набор содержит около 20 синтетических примеров; доверительный интервал шире самой метрики. Единственный осмысленный сигнал — recall high-risk классов, остальное является smoke-проверкой.",
        "",
        "Наборы разделены: обучение выполнено только на `data/tickets_train.jsonl`, метрики — только на `data/tickets_eval.jsonl`; demo-набор не использовался ни на одном этапе.",
        "",
        "## Сводка",
        "",
        "| Метрика | Значение |",
        "|---|---:|",
        f"| Macro-F1 | {macro_f1:.3f} |",
        f"| UNKNOWN | {_percent(unknown_share)} |",
        f"| Low-confidence ниже `{config.CONF_THRESHOLD}` | {_percent(low_confidence_share)} |",
        f"| p95 latency классификации | {p95_latency:.3f} ms |",
        f"| Retrieval Recall@3 на {len(_RETRIEVAL_CASES)} ручных парах | {recall_at_3:.3f} |",
        "",
        "## Классы",
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
    lines.extend([
        "",
        "## Recall high-risk классов",
        "",
    ])
    for label in sorted(_HIGH_RISK):
        lines.append(f"- `{label}`: {per_class[label][1]:.3f}")
    lines.extend([
        "",
        "## Retrieval-набор",
        "",
        "Пары запрос → `document_id` размечены вручную в `src/support_ai/evaluate.py`; измеряется попадание ожидаемого документа в top-3. Набор проверяет поиск, но слишком мал для продуктового вывода.",
        "",
        "Отчёт воспроизводится командой `.venv/bin/python -m src.support_ai.evaluate`.",
        "",
    ])
    config.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (config.DOCS_DIR / "eval_report.md").write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
