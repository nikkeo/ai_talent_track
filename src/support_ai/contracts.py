"""Единственная точка связи между модулями.
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol

Action = Literal["AUTO_RESPONSE", "DRAFT_FOR_OPERATOR", "ESCALATE"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]

# Policy принимает ровно одно решение. AUTO_RESPONSE становится возможен только
# как AUTO_CANDIDATE + релевантный источник + auto_allowed + validation.ok + записанный audit.
PolicyRoute = Literal["ESCALATE", "DRAFT_ONLY", "AUTO_CANDIDATE"]

# Два контура — два непересекающихся набора состояний. Полная целевая модель
# (QUEUED_FOR_FULFILLMENT, FULFILLING, PENDING_DELIVERY, FAILED_RETRYABLE, ...)
# описывается в docs/architecture.md вместе с переходами и их владельцами.
RoutingStatus = Literal["ROUTED", "NEEDS_HUMAN", "FAILED"]
FulfillmentStatus = Literal["COMPLETED", "NEEDS_HUMAN", "FAILED"]

# PoC пишет только два типа событий. DELIVERY_COMPLETED / DELIVERY_FAILED
# появляются вместе с dispatcher-ом и описаны в architecture.md.
AuditEventType = Literal["ROUTING_DECIDED", "FULFILLMENT_COMPLETED"]

AUDIT_SCHEMA_VERSION = "1.0"


@dataclass
class Ticket:
    """Исходное обращение. Живёт только внутри ingress и routing."""
    ticket_id: str
    customer_ref: str
    channel: Literal["chat", "email", "web", "mobile"]
    language: str
    text: str
    created_at: str
    # channel + external_ticket_id + event_version. Обязательное поле:
    # пустой ключ отключил бы дедупликацию или склеил разные тикеты.
    idempotency_key: str
    metadata: dict = field(default_factory=dict)


@dataclass
class RedactedText:
    text: str                      # текст с масками <CARD_1>, <PHONE_1>, ...
    found_types: list[str]         # ["CARD", "PHONE"]
    placeholders: int = 0


@dataclass
class SanitizedTicket:
    """Единственная форма тикета, которой разрешено пересекать границу очереди.

    Исходный Ticket за redaction не проходит: так путь «случайно отправить
    ticket.text в LLM» закрыт типом, а не дисциплиной.
    """
    ticket_id: str
    idempotency_key: str
    channel: str
    language: str
    redacted_text: str
    found_pii_types: list[str] = field(default_factory=list)
    # Явные поля вместо свободного dict: в произвольный словарь рано или поздно
    # скопируют email, телефон или имя, и PII снова окажется за границей очереди.
    product: str | None = None
    app_version: str | None = None
    platform: str | None = None
    locale: str | None = None
    incident_id: str | None = None


@dataclass
class Classification:
    topic: str                     # ... | "UNKNOWN"
    confidence: float
    topk: list[tuple[str, float]]
    model_version: str


@dataclass
class PolicyContext:
    """Всё, на чём policy имеет право строить решение, кроме самой классификации."""
    channel: str
    language: str
    found_pii_types: list[str] = field(default_factory=list)
    product: str | None = None


@dataclass
class PolicyDecision:
    route: PolicyRoute             # единственное решение policy, без противоречивых флагов
    risk_level: RiskLevel
    risk_type: str | None          # FINANCIAL | SECURITY | PRIVACY | LEGAL | None
    target_queue: str
    policy_rule_id: str
    policy_version: str
    reason: str


@dataclass
class Hit:
    doc_id: str
    title: str
    snippet: str
    score: float
    # KB governance: решение об автоответе принимает validator, retrieval только отдаёт метаданные.
    # Умолчания fail-closed: документ без явного статуса не считается опубликованным.
    auto_allowed: bool = False
    approval_status: Literal["draft", "review", "published"] = "draft"
    owner: str | None = None
    expires_at: str | None = None
    # диагностика каскадных ошибок: совпала ли тема документа с предсказанной
    doc_topics: list[str] = field(default_factory=list)
    topic_match: bool = False


@dataclass
class RetrievalResult:
    hits: list[Hit]
    max_score: float
    index_version: str
    query_topic: str | None = None
    threshold_used: float = 0.0


@dataclass
class Draft:
    text: str | None
    citations: list[str]
    mode: Literal["template", "llm", "none"]
    llm_used: bool
    degraded: bool
    reason: str = ""


@dataclass
class Validation:
    ok: bool
    failed_checks: list[str] = field(default_factory=list)


@dataclass
class RoutingDecision:
    """Итог синхронного контура. Финального действия здесь ещё нет и быть не может."""
    status: RoutingStatus
    route: PolicyRoute
    target_queue: str
    reason: str
    sync_route_ms: float


@dataclass
class Decision:
    """Итог асинхронного контура."""
    final_action: Action
    status: FulfillmentStatus
    target_queue: str
    reason: str
    answer_text: str | None
    citations: list[str]
    latency_ms: dict           # ключи sync_route_ms и async_fulfill_ms обязательны


@dataclass
class AuditEvent:
    event_type: AuditEventType
    schema_version: str
    # монотонно возрастает внутри correlation_id. В PoC событий ровно два,
    # в целевой модели их больше: attempt started / failed / retried / completed.
    sequence: int
    correlation_id: str        # весь жизненный цикл тикета
    attempt_id: str            # конкретная попытка обработки
    ticket_id: str
    idempotency_key: str
    ts: str
    versions: dict
    classification: dict | None
    policy: dict | None
    retrieval: dict | None
    draft: dict | None
    validation: dict | None
    # Раздельные поля вместо одного decision: в routing-событии и в fulfillment-событии
    # туда попадали разные по смыслу объекты, и схема была неоднозначной.
    routing_decision: dict | None
    fulfillment_decision: dict | None
    latency_ms: dict


@dataclass
class RoutingOutcome:
    """Всё, что синхронный контур передаёт асинхронному. Raw Ticket сюда не входит."""
    routing: RoutingDecision
    audit: AuditEvent
    sanitized: SanitizedTicket
    classification: Classification
    policy: PolicyDecision


@dataclass
class LLMResult:
    """Не только текст: без usage-полей раздел про контроль стоимости LLM
    в monitoring.md нечем подтвердить. Mock возвращает нули."""
    text: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    request_id: str | None = None


class LLM(Protocol):
    name: str

    def complete(self, system: str, user: str, timeout_s: float) -> LLMResult: ...
