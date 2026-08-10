"""Единственная точка связи между модулями. Менять только через Lead."""

from dataclasses import dataclass, field
from typing import Literal, Protocol

Action = Literal["AUTO_RESPONSE", "DRAFT_FOR_OPERATOR", "ESCALATE"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]


@dataclass
class Ticket:
    ticket_id: str
    customer_ref: str
    channel: Literal["chat", "email", "web", "mobile"]
    language: str
    text: str
    created_at: str
    metadata: dict = field(default_factory=dict)


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
class PolicyDecision:
    risk_level: RiskLevel
    risk_type: str | None          # FINANCIAL | SECURITY | PRIVACY | LEGAL | None
    allow_generation: bool
    allow_auto_send: bool
    action: Action                 # предварительное решение до retrieval/generation
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
    auto_allowed: bool


@dataclass
class RetrievalResult:
    hits: list[Hit]
    max_score: float
    index_version: str


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
    target_queue: str
    reason: str
    answer_text: str | None
    citations: list[str]
    latency_ms: dict


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


class LLM(Protocol):
    name: str

    def complete(self, system: str, user: str, timeout_s: float) -> str: ...
