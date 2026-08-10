"""Единственная точка связи между модулями. Менять только через Lead."""

from dataclasses import dataclass, field
from typing import Literal, Protocol

Action = Literal["AUTO_RESPONSE", "DRAFT_FOR_OPERATOR", "ESCALATE"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]

# Policy принимает ровно одно решение. AUTO_RESPONSE становится возможен только
# как AUTO_CANDIDATE + релевантный источник + auto_allowed + validation.ok + записанный audit.
PolicyRoute = Literal["ESCALATE", "DRAFT_ONLY", "AUTO_CANDIDATE"]

# Урезанная модель состояний: только то, что PoC реально наблюдает.
# Полная машина состояний асинхронного контура — в docs/architecture.md.
ProcessingStatus = Literal["RECEIVED", "ROUTED", "NEEDS_HUMAN", "COMPLETED", "FAILED"]


@dataclass
class Ticket:
    ticket_id: str
    customer_ref: str
    channel: Literal["chat", "email", "web", "mobile"]
    language: str
    text: str
    created_at: str
    metadata: dict = field(default_factory=dict)
    # channel + external_ticket_id + event_version; повторная доставка не должна
    # запускать LLM, писать второе решение и отправлять ответ дважды
    idempotency_key: str = ""


@dataclass
class RedactedText:
    text: str                      # текст с масками <CARD_1>, <PHONE_1>, ...
    found_types: list[str]         # ["CARD", "PHONE"]
    placeholders: int = 0


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
    # KB governance: решение об автоответе принимает validator, retrieval только отдаёт метаданные
    auto_allowed: bool
    owner: str | None = None
    expires_at: str | None = None
    approval_status: str = "published"   # published | draft | review
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
class Decision:
    final_action: Action
    status: ProcessingStatus
    target_queue: str
    reason: str
    answer_text: str | None
    citations: list[str]
    latency_ms: dict           # ключи sync_route_ms и async_fulfill_ms обязательны


@dataclass
class AuditEvent:
    request_id: str
    ticket_id: str
    ts: str
    versions: dict
    classification: dict | None
    policy: dict | None
    retrieval: dict | None
    draft: dict | None
    validation: dict | None
    decision: dict
    latency_ms: dict


@dataclass
class RoutingOutcome:
    """Результат синхронного контура. Всё, что нужно асинхронной части, — здесь."""
    decision: Decision
    audit: AuditEvent
    redacted: RedactedText
    classification: Classification
    policy: PolicyDecision


class LLM(Protocol):
    name: str

    def complete(self, system: str, user: str, timeout_s: float) -> str: ...
