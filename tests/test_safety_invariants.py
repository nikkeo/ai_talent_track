import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from support_ai import config
from support_ai.contracts import (
    Classification,
    Draft,
    Hit,
    LLMResult,
    PolicyDecision,
    RetrievalResult,
    Ticket,
    Validation,
)
from support_ai.pipeline import process


def ticket(text: str, *, key: str | None = None) -> Ticket:
    ticket_id = uuid4().hex
    return Ticket(
        ticket_id=ticket_id,
        customer_ref="test-customer",
        channel="chat",
        language="ru",
        text=text,
        created_at="2026-08-10T12:00:00Z",
        idempotency_key=key or f"chat:{ticket_id}:v1",
    )


def hit(doc_id: str = "KB-TECH-125") -> Hit:
    return Hit(
        doc_id=doc_id,
        title="Видео",
        snippet="Перезапустите приложение.",
        score=0.9,
        auto_allowed=True,
        approval_status="published",
        owner="support",
        expires_at="2099-01-01",
        doc_topics=["TECHNICAL"],
        topic_match=True,
    )


@pytest.fixture(autouse=True)
def isolated_audit(monkeypatch, tmp_path: Path) -> Path:
    path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(config, "AUDIT_PATH", path)
    return path


def test_high_risk_never_calls_retrieval_or_llm(monkeypatch) -> None:
    calls = {"retrieval": 0, "llm": 0}
    monkeypatch.setattr(
        "support_ai.pipeline.retrieval.search",
        lambda *args, **kwargs: calls.__setitem__("retrieval", calls["retrieval"] + 1),
    )
    monkeypatch.setattr(
        "support_ai.pipeline.llm.get_llm",
        lambda *args, **kwargs: calls.__setitem__("llm", calls["llm"] + 1),
    )

    decision, _ = process(ticket("двойное списание, верните деньги"))

    assert decision.final_action == "ESCALATE"
    assert decision.target_queue == "financial-support"
    assert calls == {"retrieval": 0, "llm": 0}


def test_raw_pii_never_reaches_components_or_audit(monkeypatch, isolated_audit: Path) -> None:
    raw_values = ["4111 1111 1111 1111", "+7 (999) 123-45-67", "demo@example.com"]
    observed: dict[str, str] = {}

    def classify(text: str) -> Classification:
        observed["classifier"] = text
        return Classification("TECHNICAL", 0.99, [("TECHNICAL", 0.99)], "test")

    def policy_override(*args) -> PolicyDecision:
        return PolicyDecision("AUTO_CANDIDATE", "LOW", None, "automation", "TEST", "test", "SAFE_TEST")

    def search(query: str, topic: str, k: int) -> RetrievalResult:
        observed["retrieval"] = query
        return RetrievalResult([hit()], 0.9, "test")

    class SpyLLM:
        name = "spy"

        def complete(self, system: str, user: str, timeout_s: float) -> LLMResult:
            observed["llm"] = f"{system}\n{user}"
            return LLMResult("Безопасный ответ", "test", "test")

    def make_draft(sanitized, retrieval, policy, llm) -> Draft:
        llm.complete("system", sanitized.redacted_text, 1.0)
        return Draft("Безопасный ответ", [retrieval.hits[0].doc_id], "llm", True, False)

    monkeypatch.setattr("support_ai.pipeline.classifier.predict", classify)
    monkeypatch.setattr("support_ai.pipeline.policy.decide", policy_override)
    monkeypatch.setattr("support_ai.pipeline.retrieval.search", search)
    monkeypatch.setattr("support_ai.pipeline.llm.get_llm", lambda mode: SpyLLM())
    monkeypatch.setattr("support_ai.pipeline.generator.make_draft", make_draft)
    monkeypatch.setattr("support_ai.pipeline.validator.validate", lambda *args: Validation(True))

    process(ticket("Видео не работает. " + ", ".join(raw_values)))

    audit_text = isolated_audit.read_text(encoding="utf-8")
    assert observed.keys() == {"classifier", "retrieval", "llm"}
    assert all(raw not in value for value in observed.values() for raw in raw_values)
    assert all(raw not in audit_text for raw in raw_values)


def test_empty_retrieval_forbids_draft(monkeypatch) -> None:
    generated = False

    def generate(*args):
        nonlocal generated
        generated = True

    monkeypatch.setattr(
        "support_ai.pipeline.retrieval.search", lambda *args, **kwargs: RetrievalResult([], 0.0, "test")
    )
    monkeypatch.setattr("support_ai.pipeline.generator.make_draft", generate)

    decision, _ = process(ticket("не воспроизводится видео в приложении"))

    assert decision.final_action == "ESCALATE"
    assert decision.reason == "NO_RELIABLE_CONTEXT"
    assert generated is False


def test_unretrieved_citation_cannot_be_auto_response(monkeypatch) -> None:
    context = RetrievalResult([hit("KB-REAL")], 0.9, "test")
    monkeypatch.setattr("support_ai.pipeline.retrieval.search", lambda *args, **kwargs: context)
    monkeypatch.setattr(
        "support_ai.pipeline.generator.make_draft",
        lambda *args: Draft("Ответ", ["KB-MISSING"], "llm", True, False),
    )

    decision, _ = process(ticket("не воспроизводится видео в приложении"))

    assert decision.final_action != "AUTO_RESPONSE"


def test_validation_failure_forbids_auto_response(monkeypatch) -> None:
    monkeypatch.setattr(
        "support_ai.pipeline.retrieval.search",
        lambda *args, **kwargs: RetrievalResult([hit()], 0.9, "test"),
    )
    monkeypatch.setattr(
        "support_ai.pipeline.generator.make_draft",
        lambda *args: Draft("Ответ", [hit().doc_id], "llm", True, False),
    )
    monkeypatch.setattr(
        "support_ai.pipeline.validator.validate", lambda *args: Validation(False, ["FORBIDDEN_PROMISE"])
    )

    decision, _ = process(ticket("не воспроизводится видео в приложении"))

    assert decision.final_action == "DRAFT_FOR_OPERATOR"
    assert "FORBIDDEN_PROMISE" in decision.reason


def test_audit_failure_forbids_auto_response(monkeypatch) -> None:
    monkeypatch.setattr("support_ai.pipeline.audit.write", lambda event: False)

    decision, _ = process(ticket("не воспроизводится видео в приложении"))

    assert decision.final_action == "ESCALATE"
    assert decision.reason == "AUDIT_WRITE_FAILED"


def test_llm_failure_has_deterministic_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "support_ai.pipeline.retrieval.search",
        lambda *args, **kwargs: RetrievalResult([hit()], 0.9, "test"),
    )
    outputs = []
    for _ in range(2):
        decision, _event = process(ticket("не воспроизводится видео в приложении"), llm_mode="fail")
        outputs.append((decision.final_action, decision.answer_text, decision.reason))

    assert outputs[0] == outputs[1]
    assert outputs[0][0] == "DRAFT_FOR_OPERATOR"


def test_idempotency_key_prevents_second_action(monkeypatch, isolated_audit: Path) -> None:
    calls = 0

    def generate(*args) -> Draft:
        nonlocal calls
        calls += 1
        return Draft("Ответ", [hit().doc_id], "llm", True, False)

    monkeypatch.setattr(
        "support_ai.pipeline.retrieval.search",
        lambda *args, **kwargs: RetrievalResult([hit()], 0.9, "test"),
    )
    monkeypatch.setattr("support_ai.pipeline.generator.make_draft", generate)
    monkeypatch.setattr("support_ai.pipeline.validator.validate", lambda *args: Validation(True))
    item = ticket("не воспроизводится видео в приложении", key=f"same:{uuid4().hex}:v1")

    first = process(item)
    second = process(replace(item, text="другой текст"))

    assert second == first
    assert calls == 1
    assert len(isolated_audit.read_text().splitlines()) == 2


def test_all_demo_scenarios_have_expected_actions(monkeypatch) -> None:
    class PassingLLM:
        name = "mock"

        def complete(self, system: str, user: str, timeout_s: float) -> LLMResult:
            return LLMResult("Безопасная инструкция", "local", "test")

    class FailingLLM:
        name = "fail"

        def complete(self, system: str, user: str, timeout_s: float) -> LLMResult:
            raise TimeoutError

    def make_draft(sanitized, retrieval, policy, llm_client) -> Draft:
        try:
            result = llm_client.complete("system", sanitized.redacted_text, 1.0)
            return Draft(result.text, [retrieval.hits[0].doc_id], "llm", True, False)
        except TimeoutError:
            return Draft("Шаблон оператора", [retrieval.hits[0].doc_id], "template", False, True, "LLM_FAILED_TEMPLATE_FALLBACK")

    monkeypatch.setattr(
        "support_ai.pipeline.llm.get_llm", lambda mode: FailingLLM() if mode == "fail" else PassingLLM()
    )
    monkeypatch.setattr("support_ai.pipeline.generator.make_draft", make_draft)
    monkeypatch.setattr("support_ai.pipeline.validator.validate", lambda *args: Validation(True))
    rows = [json.loads(line) for line in config.DEMO_TICKETS.read_text().splitlines()]
    expected = {
        "S1": ("DRAFT_FOR_OPERATOR", "general", "VALIDATION_FAILED:LOW_RELEVANCE_FOR_AUTO"),
        "S2": ("ESCALATE", "financial-support", "HIGH_RISK_FINANCIAL"),
        "S3": ("DRAFT_FOR_OPERATOR", "general", "LLM_FAILED_TEMPLATE_FALLBACK"),
        "S4": ("ESCALATE", "general", "LOW_CONFIDENCE"),
        "S5": ("ESCALATE", "general", "NO_RELIABLE_CONTEXT"),
        "S6": ("ESCALATE", "financial-support", "HIGH_RISK_FINANCIAL"),
    }

    for row in rows:
        mode = "fail" if row["ticket_id"] == "S3" else "mock"
        decision, _ = process(Ticket(**row), llm_mode=mode)
        assert (decision.final_action, decision.target_queue, decision.reason) == expected[row["ticket_id"]]
        assert decision.latency_ms["sync_route_ms"] < 500
