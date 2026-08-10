"""Fail-closed orchestration of synchronous routing and asynchronous fulfillment."""

from dataclasses import asdict
from datetime import UTC, datetime
from threading import Lock
from time import perf_counter
from uuid import uuid4

from . import audit, classifier, config, generator, llm, policy, retrieval, validator
from .contracts import (
    AUDIT_SCHEMA_VERSION,
    AuditEvent,
    Decision,
    Draft,
    PolicyContext,
    PolicyDecision,
    RetrievalResult,
    RoutingDecision,
    RoutingOutcome,
    SanitizedTicket,
    Ticket,
    Validation,
)
from .normalize import detect_language, normalize
from .pii import redact


_completed: dict[str, tuple[Decision, AuditEvent]] = {}
_completed_lock = Lock()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _failure_policy(reason: str) -> PolicyDecision:
    return PolicyDecision(
        route="ESCALATE",
        risk_level="HIGH",
        risk_type=None,
        target_queue="general",
        policy_rule_id="FAIL-CLOSED",
        policy_version=config.VERSIONS["policy"],
        reason=reason,
    )


def _routing_event(
    outcome_data: tuple[SanitizedTicket, object, PolicyDecision, RoutingDecision],
    correlation_id: str,
    attempt_id: str,
) -> AuditEvent:
    sanitized, classification, policy_decision, routing = outcome_data
    classification_data = asdict(classification)  # type: ignore[arg-type]
    classification_data["redacted_text"] = sanitized.redacted_text
    return AuditEvent(
        event_type="ROUTING_DECIDED",
        schema_version=AUDIT_SCHEMA_VERSION,
        sequence=1,
        correlation_id=correlation_id,
        attempt_id=attempt_id,
        ticket_id=sanitized.ticket_id,
        idempotency_key=sanitized.idempotency_key,
        ts=_now(),
        versions=config.runtime_versions("pending"),
        classification=classification_data,
        policy=asdict(policy_decision),
        retrieval=None,
        draft=None,
        validation=None,
        routing_decision=asdict(routing),
        fulfillment_decision=None,
        latency_ms={"sync_route_ms": routing.sync_route_ms},
    )


def route(ticket: Ticket, *, faults: frozenset[str] = frozenset()) -> RoutingOutcome:
    """Synchronously sanitize, classify, apply policy and persist the routing decision."""
    started = perf_counter()
    normalized = normalize(ticket)
    redacted, _mask_map = redact(normalized)
    sanitized = SanitizedTicket(
        ticket_id=ticket.ticket_id,
        idempotency_key=ticket.idempotency_key,
        channel=ticket.channel,
        language=detect_language(normalized),
        redacted_text=redacted.text,
        found_pii_types=redacted.found_types,
        product=ticket.metadata.get("product"),
        app_version=ticket.metadata.get("app_version"),
        platform=ticket.metadata.get("platform"),
        locale=ticket.metadata.get("locale"),
        incident_id=ticket.metadata.get("incident_id"),
    )
    classification = classifier.predict(sanitized.redacted_text)
    context = PolicyContext(
        channel=sanitized.channel,
        language=sanitized.language,
        found_pii_types=sanitized.found_pii_types,
        product=sanitized.product,
    )
    policy_decision = (
        _failure_policy("POLICY_UNAVAILABLE")
        if "policy" in faults
        else policy.decide(classification, redacted, context)
    )
    elapsed_ms = (perf_counter() - started) * 1_000
    routing = RoutingDecision(
        status="NEEDS_HUMAN" if policy_decision.route == "ESCALATE" else "ROUTED",
        route=policy_decision.route,
        target_queue=policy_decision.target_queue,
        reason=policy_decision.reason,
        sync_route_ms=elapsed_ms,
    )
    event = _routing_event((sanitized, classification, policy_decision, routing), str(uuid4()), str(uuid4()))
    written = False if "audit" in faults else audit.write(event)
    if not written:
        policy_decision = _failure_policy("AUDIT_WRITE_FAILED")
        routing = RoutingDecision(
            status="FAILED",
            route="ESCALATE",
            target_queue="general",
            reason="AUDIT_WRITE_FAILED",
            sync_route_ms=(perf_counter() - started) * 1_000,
        )
        event.policy = asdict(policy_decision)
        event.routing_decision = asdict(routing)
        event.latency_ms = {"sync_route_ms": routing.sync_route_ms}
    return RoutingOutcome(routing, event, sanitized, classification, policy_decision)


def _decision(
    outcome: RoutingOutcome,
    action: str,
    reason: str,
    async_ms: float,
    *,
    answer: str | None = None,
    citations: list[str] | None = None,
) -> Decision:
    return Decision(
        final_action=action,  # type: ignore[arg-type]
        status="COMPLETED" if action == "AUTO_RESPONSE" else "NEEDS_HUMAN",
        target_queue=outcome.policy.target_queue,
        reason=reason,
        answer_text=answer,
        citations=citations or [],
        latency_ms={
            "sync_route_ms": outcome.routing.sync_route_ms,
            "async_fulfill_ms": async_ms,
        },
    )


def _fulfillment_event(
    outcome: RoutingOutcome,
    decision: Decision,
    retrieval_result: RetrievalResult,
    draft: Draft | None,
    validation: Validation | None,
    llm_mode: str,
) -> AuditEvent:
    draft_data = asdict(draft) if draft is not None else None
    return AuditEvent(
        event_type="FULFILLMENT_COMPLETED",
        schema_version=AUDIT_SCHEMA_VERSION,
        sequence=2,
        correlation_id=outcome.audit.correlation_id,
        attempt_id=outcome.audit.attempt_id,
        ticket_id=outcome.sanitized.ticket_id,
        idempotency_key=outcome.sanitized.idempotency_key,
        ts=_now(),
        versions=config.runtime_versions(llm_mode),
        classification=asdict(outcome.classification),
        policy=asdict(outcome.policy),
        retrieval=asdict(retrieval_result),
        draft=draft_data,
        validation=asdict(validation) if validation is not None else None,
        routing_decision=asdict(outcome.routing),
        fulfillment_decision=asdict(decision),
        latency_ms=decision.latency_ms,
    )


def fulfill(
    outcome: RoutingOutcome,
    *,
    llm_mode: str = "mock",
    faults: frozenset[str] = frozenset(),
) -> tuple[Decision, AuditEvent]:
    """Retrieve context, generate and validate a draft, then audit before action."""
    started = perf_counter()
    if outcome.policy.route == "ESCALATE":
        decision = _decision(outcome, "ESCALATE", outcome.policy.reason, 0.0)
        return decision, outcome.audit

    try:
        retrieval_result = (
            RetrievalResult([], 0.0, config.VERSIONS["kb_index"])
            if "retrieval" in faults
            else retrieval.search(
                outcome.sanitized.redacted_text,
                outcome.classification.topic,
                k=config.RETRIEVAL_TOP_K,
            )
        )
    except Exception:
        retrieval_result = RetrievalResult([], 0.0, config.VERSIONS["kb_index"])

    if not retrieval_result.hits or retrieval_result.max_score < config.RELEVANCE_THRESHOLD:
        decision = _decision(
            outcome,
            "ESCALATE",
            "NO_RELIABLE_CONTEXT",
            (perf_counter() - started) * 1_000,
        )
        event = _fulfillment_event(outcome, decision, retrieval_result, None, None, llm_mode)
        written = False if "audit" in faults else audit.write(event)
        if not written:
            decision.reason = "AUDIT_WRITE_FAILED"
            event.fulfillment_decision = asdict(decision)
        return decision, event

    draft: Draft
    try:
        draft = generator.make_draft(
            outcome.sanitized,
            retrieval_result,
            outcome.policy,
            llm.get_llm("fail" if "llm" in faults else llm_mode),
        )
    except Exception:
        draft = Draft(None, [], "none", False, True, "LLM_UNAVAILABLE")

    validation = validator.validate(draft, retrieval_result, outcome.policy)
    async_ms = (perf_counter() - started) * 1_000
    if draft.degraded:
        decision = _decision(
            outcome, "DRAFT_FOR_OPERATOR", draft.reason or "GENERATION_DEGRADED", async_ms,
            answer=draft.text, citations=draft.citations,
        )
    elif not validation.ok:
        reason = "VALIDATION_FAILED:" + ",".join(validation.failed_checks)
        decision = _decision(
            outcome, "DRAFT_FOR_OPERATOR", reason, async_ms,
            answer=draft.text, citations=draft.citations,
        )
    elif outcome.policy.route != "AUTO_CANDIDATE":
        decision = _decision(
            outcome, "DRAFT_FOR_OPERATOR", "POLICY_DRAFT_ONLY", async_ms,
            answer=draft.text, citations=draft.citations,
        )
    else:
        decision = _decision(
            outcome, "AUTO_RESPONSE", "VALIDATED_AUTO_RESPONSE", async_ms,
            answer=draft.text, citations=draft.citations,
        )

    event = _fulfillment_event(outcome, decision, retrieval_result, draft, validation, llm_mode)
    written = False if "audit" in faults else audit.write(event)
    if not written:
        decision = _decision(outcome, "ESCALATE", "AUDIT_WRITE_FAILED", async_ms)
        event.fulfillment_decision = asdict(decision)
    return decision, event


def process(
    ticket: Ticket,
    *,
    llm_mode: str = "mock",
    faults: frozenset[str] = frozenset(),
) -> tuple[Decision, AuditEvent]:
    """Run both contours with in-memory idempotency for completed decisions."""
    with _completed_lock:
        cached = _completed.get(ticket.idempotency_key)
    if cached is not None:
        return cached

    outcome = route(ticket, faults=faults)
    result = fulfill(outcome, llm_mode=llm_mode, faults=faults)
    with _completed_lock:
        return _completed.setdefault(ticket.idempotency_key, result)
