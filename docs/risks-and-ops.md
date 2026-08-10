# Риски и эксплуатация

> **Audience: For everyone**

Структура очередей, outbox и целевые переходы принадлежат
[architecture.md](architecture.md). Здесь описаны только рабочее поведение и
пределы текущего PoC.

## Высокая нагрузка и надёжность

1. **Профиль нагрузки и граница контуров.** 200 000 тикетов/сутки — около 2,3 RPS
   в среднем; пик 20 000 за 10 минут — около 33 RPS, то есть ×14. В
   `pipeline.route()` синхронны только normalize, redaction, classification,
   policy и запись `ROUTING_DECIDED`: пользователь быстро получает безопасный
   маршрут. Retrieval, generation и validation находятся в `fulfill()`; в PoC он
   вызывается inline, его фактический вынос в worker **спроектирован, не реализован**.

2. **Отказы не превращаются в автоматическое действие.** Недоступная policy даёт
   `POLICY_UNAVAILABLE`, retrieval — `NO_RELIABLE_CONTEXT`, а отказ LLM в
   `generator.make_draft()` даёт детерминированный шаблон и максимум
   `DRAFT_FOR_OPERATOR`. `Draft.degraded`, провал validation и отсутствие статьи
   также запрещают `AUTO_RESPONSE`. Circuit breaker **не реализован**; безопасный
   fallback работает для каждого запроса независимо.

3. **Backpressure.** Для production спроектированы, но не реализованы: лимит
   параллельных LLM-вызовов, приоритет incident/high-priority сообщений, отключение
   необязательной генерации при перегрузке, заранее утверждённые incident-шаблоны и
   дедупликация массового одинакового всплеска. High-risk и low-confidence уже
   short-circuit до retrieval, поэтому не занимают дорогую очередь генерации.

4. **Идемпотентность и восстановление.** `pipeline.process()` хранит первое решение
   по обязательному `idempotency_key` в in-memory словаре: повтор не вызывает LLM
   и не пишет второй audit. Это честное упрощение PoC — состояние теряется при
   рестарте, не разделяется между процессами и не защищает от одновременной гонки
   двух workers. Durable idempotency store и retry/outbox **спроектированы, не
   реализованы**; JSONL audit намеренно не используется как индекс.

## Приватность, безопасность и human-in-the-loop

1. **PII-граница обеспечена типом.** `normalize → pii.redact` выполняются до
   classifier; за границу `route()` передаётся только `SanitizedTicket`, где нет
   raw text, `customer_ref` и свободного metadata. Копируются только `product`,
   `app_version`, `platform`, `locale`, `incident_id`. Карты с проверкой Луна,
   телефоны, email, паспорт и токены заменяются плейсхолдерами; карта масок остаётся
   локальной переменной и не входит в retrieval, LLM или audit. Это проверяет
   safety-инвариант №2 в `tests/test_safety_invariants.py`.

2. **Запрещённые категории.** Правила `SEC-001`, `PRIV-001`, `LEG-001` и `FIN-001`
   всегда отправляют соответственно security, privacy, legal и financial обращения
   человеку до retrieval. Уверенность классификатора не отменяет правило; наличие
   `<CARD_n>` — дополнительный financial-сигнал. `LOW-001` передаёт человеку
   неизвестные и low-confidence запросы. Для остальных human-in-the-loop остаётся
   при `DRAFT_ONLY`, degraded generation или failed validation.

3. **Prompt injection и полномочия генератора.** В генератор поступают только
   `SanitizedTicket`, найденный фрагмент и уже принятое `PolicyDecision`; тикет и
   статья трактуются prompt-ом как данные, а не инструкции. Генератор возвращает
   лишь `Draft` и не может изменить route. Validator отдельно проверяет citation,
   governance статьи, PII, запрещённые обещания и длину. Более сильная изоляция
   внешнего provider и adversarial regression suite **спроектированы, не
   реализованы**.

4. **Audit до действия.** `audit.write()` append-only записывает версии, решения,
   retrieval, validation, latency и LLM usage до возврата действия. Если запись не
   удалась, pipeline заменяет результат на `ESCALATE`: «нет записи — нет
   автодействия». Ограничение PoC: при полном отказе audit не запишется и сам факт
   эскалации; тикет остаётся у оператора, а отказ должен быть виден отдельным
   счётчиком `audit_write_failed`. Доставка счётчика во внешнюю систему мониторинга
   **спроектирована, не реализована**.
