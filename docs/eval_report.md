# Offline-отчёт

> **Ограничение:** eval-набор содержит около 20 синтетических примеров; доверительный интервал шире самой метрики. Осмысленные safety-сигналы здесь — model recall high-risk и policy-level recall риска; остальные значения являются smoke-проверкой.

Наборы разделены: обучение выполнено только на `data/tickets_train.jsonl`, метрики — только на `data/tickets_eval.jsonl`; demo-набор не использовался ни на одном этапе.

## Сводка на текущем config

| Метрика | Значение |
|---|---:|
| CONF_THRESHOLD | 0.30 |
| Macro-F1 | 0.892 |
| Model recall high-risk macro | 0.667 |
| Policy recall high-risk с корректным `risk_type` | 0.778 |
| UNKNOWN | 15.0% |
| Low-confidence | 15.0% |
| p95 latency классификации | 0.164 ms |
| Retrieval Recall@3 на 10 ручных парах | 1.000 |

Model recall требует точного класса от классификатора. Policy recall считает high-risk тикеты, для которых `policy.decide` вернул `ESCALATE` и правильный `risk_type`; это разные границы качества.

## Сквозной прогон: что система сделала бы с eval-набором

| Метрика | Значение |
|---|---:|
| Automation rate (AUTO_RESPONSE) | 0.0% |
| Draft rate (оператору с черновиком) | 0.0% |
| Escalation rate | 100.0% |
| Небезопасная автоматизация high-risk | 0 |

Последняя строка — главный guardrail: high-risk тикет, не ушедший в `ESCALATE`. Любое значение больше нуля блокирует включение автоответов.

## Классы на текущем config

| Класс | Precision | Recall | F1 | Support | High-risk |
|---|---:|---:|---:|---:|:---:|
| ACCOUNT_ACCESS | 1.000 | 1.000 | 1.000 | 2 | нет |
| HOWTO | 1.000 | 1.000 | 1.000 | 3 | нет |
| PAYMENT | 1.000 | 0.667 | 0.800 | 3 | да |
| PRIVACY | 1.000 | 0.500 | 0.667 | 2 | да |
| REFUND | 1.000 | 0.500 | 0.667 | 2 | да |
| SECURITY | 1.000 | 1.000 | 1.000 | 2 | да |
| STATUS | 1.000 | 1.000 | 1.000 | 3 | нет |
| TECHNICAL | 1.000 | 1.000 | 1.000 | 3 | нет |

## Recall high-risk классов модели

- `PAYMENT`: 0.667
- `PRIVACY`: 0.500
- `REFUND`: 0.500
- `SECURITY`: 1.000

## Свип CONF_THRESHOLD по стоимости решений

`config.py` не изменялся. Для каждой точки evaluator локально применяет кандидат к `Classification` и `policy.decide`, затем восстанавливает runtime-config.

| Threshold | Macro-F1 | Model risk recall | Policy risk recall | UNKNOWN | unsafe_auto | wrong_route | extra escalation | operator edit | Cost |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.30 | 0.892 | 0.667 | 0.778 | 15.0% | 0 | 0 | 0 | 0 | 0 |
| 0.35 | 0.808 | 0.542 | 0.667 | 20.0% | 0 | 0 | 0 | 0 | 0 |
| 0.40 | 0.742 | 0.542 | 0.667 | 30.0% | 0 | 0 | 2 | 0 | 10 |
| 0.45 | 0.621 | 0.458 | 0.667 | 40.0% | 0 | 0 | 3 | 0 | 15 |
| 0.50 | 0.621 | 0.458 | 0.667 | 40.0% | 0 | 0 | 3 | 0 | 15 |
| 0.55 | 0.508 | 0.375 | 0.556 | 55.0% | 0 | 0 | 5 | 0 | 25 |
| 0.60 | 0.471 | 0.375 | 0.556 | 60.0% | 0 | 0 | 6 | 0 | 30 |
| 0.65 | 0.271 | 0.125 | 0.556 | 80.0% | 0 | 0 | 8 | 0 | 40 |
| 0.70 | 0.146 | 0.125 | 0.556 | 90.0% | 0 | 0 | 10 | 0 | 50 |

Выбран кандидат `0.30`: минимальная стоимость `0`. При равной стоимости tie-break предпочитает больший policy risk recall, затем model risk recall и меньшую долю UNKNOWN. Это выбор по последствиям решений, а не по максимуму F1.

Свип выявил policy-gap: при выбранном пороге policy recall с корректным `risk_type` равен `0.778`, а не близок к 1.0. Текущие правила не распознают часть eval-формулировок PRIVACY и SECURITY; LOW-001 эскалирует low-confidence случаи, но оставляет `risk_type=None`. Снижение порога повышает model recall, однако открывает больше high-risk решений без `ESCALATE`, что штрафуется по 1000.

Cost = `1000 × unsafe_auto + 50 × wrong_route + 5 × extra escalation + 1 × operator edit`. По условию эксперимента `unsafe_auto` означает любой high-risk тикет с route не `ESCALATE`, включая `DRAFT_ONLY`.

## Retrieval-набор

Пары запрос → `document_id` размечены вручную в `src/support_ai/evaluate.py`; измеряется попадание ожидаемого документа в top-3. Набор проверяет поиск, но слишком мал для продуктового вывода.

Отчёт воспроизводится командой `.venv/bin/python -m support_ai.evaluate` с `PYTHONPATH=src` или целью `make eval`.
