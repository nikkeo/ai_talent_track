# Архитектура обработки обращений

## Реализовано и спроектировано

| Возможность | PoC | Целевая система |
|---|---|---|
| Приём и нормализация | Локальный Python ingress | Адаптеры каналов с аутентификацией и rate limit |
| Защита PII | Redaction до границы очереди | DLP, шифрование и отдельный PII vault |
| Классификация | TF-IDF и Logistic Regression | Версионируемый model service с canary rollout |
| Policy | Детерминированные fail-closed правила | Версионируемый policy service с four-eyes review |
| Асинхронность | `fulfill` вызывается inline | Durable queue, retry scheduler и DLQ |
| Идемпотентность | In-memory словарь решений | Decision Store с unique index по `idempotency_key` |
| Аудит | Два события в JSONL | Append-only журнал с контролем целостности и schema registry |
| База знаний | Markdown и ленивый TF-IDF индекс | CMS, approval workflow и обновляемый hybrid index |
| Генерация | Детерминированный mock и template fallback | Внешняя LLM за rate limiter и circuit breaker |
| Доставка | Решение и текст без реального dispatcher | Второй outbox, idempotent dispatcher и delivery events |

Это разграничение принципиально: ниже проектные свойства не выдаются за гарантии текущего кода.

## Схема

```mermaid
flowchart LR
    CH[Support Channel] --> IN[Ingress]
    IN --> TS[Ticket Store]
    IN --> PII[PII Redaction]
    PII --> CL[Classifier]
    CL --> PO[Policy]
    PO --> DS[Decision Store]
    DS --> O1[Routing Outbox]
    O1 --> Q[Fulfillment Queue]
    Q --> RT[Retrieval]
    KB[KB Index] --> RT
    RT --> GE[Draft Generator]
    GE --> VA[Validator]
    LLM[External LLM] --> GE
    VA --> DS
    DS --> O2[Delivery Outbox]
    O2 --> RD[Response Dispatcher]
    RD --> CH
    VA --> HQ[Human Queue]
    PO --> HQ
    IN --> AL[Audit Log]
    PO --> AL
    VA --> AL
    RD --> AL
    HQ --> FB[Feedback Store]
```

## Компоненты и поток данных

| Компонент | Зачем он существует |
|---|---|
| Ingress и normalizer | Создают единый контракт и ключ идемпотентности для разных каналов. |
| PII redaction | Закрывает типом путь передачи исходных персональных данных за routing-контур. |
| Classifier | Даёт дешёвый, быстрый и воспроизводимый сигнал темы. |
| Policy | Сохраняет бизнес-риск детерминированным и независимым от вероятностных моделей. |
| Retrieval | Привязывает ответ к управляемому знанию и возвращает governance-метаданные. |
| Draft generator | Создаёт только текстовый черновик и безопасно деградирует без LLM. |
| Validator | Единолично выдаёт право на auto-response после grounding, governance и safety-проверок. |
| Decision Store и outbox | Делают решение идемпотентным и не дают потерять последующее задание. |
| Audit Log | Позволяет восстановить причины решения, версии и попытки без роли operational state. |
| Dispatcher и Human Queue | Разделяют надёжную доставку и обработку, требующую человеческого решения. |

Поток начинается с канального события. Ingress проверяет обязательный `idempotency_key`, сохраняет исходный тикет в защищённый Ticket Store, нормализует и маскирует PII. Classifier возвращает тему, confidence и top-3, затем policy либо немедленно направляет риск оператору, либо разрешает асинхронное наполнение. Routing decision и fulfillment job фиксируются одной транзакцией.

Worker получает только `SanitizedTicket`, ищет контекст, формирует draft и передаёт его validator. Низкая релевантность прекращает генерацию. Validator сверяет citation с найденными hits, `auto_allowed`, публикацию, owner, срок действия, PII, обещания и лимит `1200` символов. Успех для `AUTO_CANDIDATE` создаёт финальное решение и delivery job; любой запрет создаёт operator job. LLM создаёт только текстовый draft и никогда не выполняет возврат средств, блокировку аккаунта или изменение подписки.

## Синхронный и асинхронный контуры

Синхронная граница: ingress → PII → classify → policy → persist audit → route. Её бюджет — менее 500 мс. PoC пишет фактическое значение в `RoutingDecision.sync_route_ms`; итоговую цифру интеграционного demo нельзя честно зафиксировать до объединения routing-модулей. Retrieval и LLM не входят в этот SLA, поэтому их отказ не задерживает первичную операторскую маршрутизацию.

Асинхронная граница: queue → retrieval → draft → validate → final outbox. В PoC этот контур вызывается inline и виден только через `FulfillmentStatus`; durable queue и dispatcher спроектированы. Приоритет задания на human routing всегда выше генерации: тикет не ждёт освобождения LLM-квоты, чтобы попасть оператору.

Полная целевая машина состояний:

| Из | В | Владелец перехода |
|---|---|---|
| `RECEIVED` | `ROUTED` | Routing orchestrator после policy и первого outbox commit |
| `ROUTED` | `NEEDS_HUMAN` | Policy adapter для запретного или неопределённого случая |
| `ROUTED` | `QUEUED_FOR_FULFILLMENT` | Routing outbox publisher |
| `QUEUED_FOR_FULFILLMENT` | `FULFILLING` | Fulfillment worker после lease задания |
| `FULFILLING` | `VALIDATING` | Draft generator после template или LLM draft |
| `FULFILLING` | `NEEDS_HUMAN` | Fulfillment worker при отсутствии надёжного контекста |
| `FULFILLING` | `FAILED_RETRYABLE` | Fulfillment worker при временной инфраструктурной ошибке |
| `VALIDATING` | `PENDING_DELIVERY` | Validator и транзакция финального outbox |
| `VALIDATING` | `NEEDS_HUMAN` | Validator при любой непройденной проверке |
| `PENDING_DELIVERY` | `COMPLETED` | Response Dispatcher после подтверждения канала |
| `PENDING_DELIVERY` | `FAILED_RETRYABLE` | Response Dispatcher при временном отказе канала |
| `FAILED_RETRYABLE` | `QUEUED_FOR_FULFILLMENT` | Retry scheduler в пределах TTL и лимита попыток |
| `FAILED_RETRYABLE` | `FAILED_FINAL` | Retry scheduler после исчерпания попыток или TTL |
| `NEEDS_HUMAN` | `COMPLETED` | Ticketing adapter после решения оператора |

В коде PoC существуют лишь наблюдаемые `RoutingStatus` и `FulfillmentStatus`; полная машина — target design. У событий общий `correlation_id`, а `sequence` монотонно растёт внутри него. Новый retry получает новый `attempt_id`. На попытку допустимо больше двух событий: started, failed, retried и completed. Формулировка «ровно два события» относится только к упрощённому PoC с `ROUTING_DECIDED` и `FULFILLMENT_COMPLETED`.

## Хранилища

| Хранилище | Содержимое | Source of truth | Retention | PII | Консистентность |
|---|---|---|---|---|---|
| Ticket Store | Исходный текст, канал, customer reference, encrypted metadata | Да, для исходного обращения | По договору и политике удаления, например 1 год | Да | Strong write; чтение по least privilege |
| Decision Store и два outbox | Routing и final decisions, state, idempotency key, jobs | Да, для состояния и идемпотентности | Срок тикета плюс окно разбирательств | Только ссылки и маскированные данные | ACID внутри каждой границы; outbox publish eventual |
| Immutable Audit Log | Версии, причины, метрики, transitions и attempts | Да, для доказательства решения, но не для dedupe | По требованиям аудита, например 3 года | Нет исходного текста; маски минимизируются | Append-only, последовательность на correlation id |
| KB CMS и Index | Статьи, owner, approval, expiry, векторы и lexical index | CMS для контента; индекс производный | История версий без бессрочного serving старого документа | Нет | CMS strong; индекс eventual и версионирован |
| Feedback и Labeling Store | Принятие draft, diff, итоговая категория, reopen, CSAT, reject reason | Да, для обучающих labels после review | По циклу обучения и privacy policy | Псевдонимизированные признаки | Append и периодические immutable snapshots |

Source of truth идемпотентности — Decision Store с unique index по `idempotency_key`, не audit log. В PoC эту роль играет in-memory словарь: он теряется при рестарте и не координирует несколько процессов.

## Интеграции, очереди и два outbox

| Интеграция | Timeout и retry | Идемпотентность | Поведение при отказе |
|---|---|---|---|
| Входные каналы | Target: быстрый ack до 500 мс, повтор по contract канала | `channel + external_ticket_id + event_version` | Дубликат возвращает сохранённое решение; невалидное событие в quarantine |
| Ticketing API и Human Queue | Target: 2 с, exponential backoff, максимум 3 попытки | Stable operator-job key | Временная ошибка в retry queue, затем DLQ; routing к человеку не зависит от LLM |
| LLM API | В PoC `LLM_TIMEOUT_S = 2.0`; target — максимум 2 короткие попытки в пределах job TTL | Request key на attempt и сохранённый draft | Timeout, rate limit или circuit open дают approved template либо оператора |
| Support Channel delivery | Target: 2 с, exponential backoff, максимум 3 попытки | Stable delivery key и dedupe у dispatcher | Retry до TTL относительно SLA, затем `DELIVERY_FAILED` и оператор |

У очередей есть ограничение concurrency, отдельные приоритеты, TTL задания относительно SLA и DLQ. Rate limiter внешней LLM учитывает provider quota; worker не создаёт неограниченный параллелизм. Retry разрешён только для временных ошибок. Circuit breaker защищает только внешнюю LLM и никогда не отключает classifier, policy или human routing. В текущем PoC circuit breaker не реализован: fallback действует на один запрос.

Нужны два transactional outbox. Первый атомарно фиксирует `routing decision + fulfillment job`; второй — `final decision + delivery/operator job`. Иначе процесс может упасть после audit/decision commit, но до публикации задания, и тикет потеряется. JSONL в PoC — вырожденный outbox без транзакционной связи с durable state.

Delivery flow: `Decision Store + Outbox → Response Dispatcher → Support Channel`. `AUTO_RESPONSE` означает не «текст сформирован», а «создано надёжное задание на отправку». Dispatcher отправляет идемпотентно и отдельно пишет `DELIVERY_COMPLETED` или `DELIVERY_FAILED`; этих событий в PoC нет. Outbox даёт at-least-once, а дедупликация доставки — effectively-once. Гарантировать exactly-once через внешнюю границу нельзя.

## Человек, обратная связь и деградация

Оператор получает рискованные темы, low-confidence, `UNKNOWN`, отсутствие контекста и любой draft, не прошедший validator. Интерфейс фиксирует принятие draft, объём правки, фактическую категорию, причину отклонения, reopen и CSAT. После privacy-фильтра и временного split эти сигналы попадают в evaluation dataset; они ценнее усложнения prompt.

Отказ policy всегда закрывает автоматизацию. Отказ retrieval или низкий score исключает генерацию. Ошибка LLM даёт локальный approved template; отсутствие безопасного template ведёт к человеку. Просроченная, review-статья либо PII в ответе блокируются validator. Поведение под нагрузкой и эксплуатационные пределы вынесены в [риски и эксплуатацию](risks-and-ops.md), здесь задана только структура очередей и восстановления.

## Почему не микросервисы

Расчётные 33 RPS не оправдывают распределённость сами по себе. PoC — модульный монолит: меньше сетевых границ, проще воспроизводимость и безопасная сдача. В target classifier и generation можно разнести из-за разных SLA, стоимости, scaling profile и характера отказов, а не из-за текущей нагрузки. Policy и human routing должны оставаться доступными независимо от внешней LLM.
