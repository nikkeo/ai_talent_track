# Мониторинг

## Технический контур

Основной источник — `AuditEvent`: `event_type`, `ts`, `correlation_id`, `sequence`,
`latency_ms`, `routing_decision`, `fulfillment_decision`, `retrieval`, `draft` и
`validation`. Считаем throughput по `ROUTING_DECIDED`, а завершение — по
`FULFILLMENT_COMPLETED`; разница скоростей и возраст незавершённых correlation ID
показывают backlog. Отдельно нужны инфраструктурные счётчики, которых нет в JSONL:
`audit_write_failed`, timeout/error rate по компонентам и queue depth/oldest age.

Локальный прогон 10 августа 2026: 600 обработок шести сценариев, прогретая модель,
Python 3.14, mock LLM, последовательный запуск с реальной записью audit. Получено
1 625 тикетов/с; `sync_route_ms` p50/p95/p99 = **0,183/0,214/0,239 мс**,
`async_fulfill_ms` = **0,142/0,362/0,393 мс**, полный вызов =
**0,713/0,942/1,177 мс**. Прогретый `classifier.predict()` на 200 вызовах:
p95 **0,148 мс**. Это baseline PoC на локальных данных, а не обещание production:
внешняя LLM радикально изменит async latency. Панель показывает p50/p95/p99 по
каждому этапу, throughput, error/timeout rate, queue depth и oldest-message age;
`sync_route_ms` сверяется с бюджетом 500 мс.

## ML и качество решений

Из `classification.topic`, `confidence` и `topk` строим распределение классов,
confidence histogram, доли `UNKNOWN` и `LOW_CONFIDENCE`; из `policy.policy_rule_id`
— escalation rate и причины short-circuit. По delayed labels от операторов считаем
precision/recall по темам, confusion matrix и operator acceptance rate черновиков.
Для входного drift храним агрегаты длины, языка, доли пустых/неизвестных токенов и
распределения TF-IDF-признаков; текст и PII для мониторинга не сохраняем.

Чтобы отличить сдвиг входа от деградации модели, рядом сравниваем две панели:

1. **Input & confidence:** drift признаков, темы, язык, `UNKNOWN`, low-confidence.
2. **Delayed quality:** precision/recall, confusion matrix и acceptance на
   фиксированной контрольной выборке и свежих размеченных тикетах.

Если первая панель меняется, `UNKNOWN` растёт, а качество на фиксированном наборе
стабильно — это input drift. Если входное распределение стабильно, но падают
delayed quality и качество фиксированного набора — деградировала модель или её
окружение. Одновременное изменение требует сегментации по каналу, продукту и версии.

## Продукт и стоимость

Панель результата объединяет automation rate (`AUTO_RESPONSE` / все решения), FRT,
SLA breach, reopen rate, CSAT и cost per resolved ticket. Сам по себе рост
автоматизации не доказывает пользу: automation rate показываем на одном графике с
CSAT и reopen и сравниваем с постоянной holdout-группой, где отвечает оператор.
Смотрим доверительные интервалы и сегменты; успешен вариант, который сокращает FRT
без ухудшения CSAT, reopen и SLA.

Для LLM используем `draft.llm_used`, `draft.mode` и
`draft.llm_usage.{prompt_tokens,completion_tokens,latency_ms}`. По таблице цен
провайдера вычисляем токены и стоимость на тикет, cost per resolved ticket, долю
тикетов с генерацией и шаблонным fallback. Дневной budget guard предупреждает до
исчерпания лимита; скачок средней длины prompt проверяется отдельно, поскольку он
может увеличить стоимость раньше, чем изменится число генераций.

## Стартовые алерты

- p95 `sync_route_ms > 500 мс` 5 минут — критический, нарушена ingress-граница.
- `audit_write_failed > 0` за 5 минут — критический: автоматические действия закрыты.
- error или timeout rate любого компонента `> 2%` за 10 минут; LLM `> 5%` — warning
  при работающем fallback, `> 20%` — incident.
- queue oldest age `> 5 минут` или depth растёт 15 минут — включить backpressure.
- `UNKNOWN > 15%` либо рост на 5 п.п. к семидневному baseline за час — проверить drift.
- escalation rate вырос на 10 п.п. к baseline при сопоставимом трафике — проверить
  policy, KB coverage и модель.
- дневная стоимость LLM достигла 80% бюджета — warning, 100% — отключить генерацию;
  средние prompt tokens `> 1,5×` семидневного baseline — отдельный warning.
- automation rate вырос на 10 п.п., а reopen ухудшился на 3 п.п. или CSAT на 0,3 —
  остановить расширение автоответов и сверить holdout.
