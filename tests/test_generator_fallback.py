from support_ai.contracts import (
    Draft,
    Hit,
    LLMResult,
    PolicyDecision,
    RetrievalResult,
    SanitizedTicket,
)
from support_ai.generator import make_draft
from support_ai.llm import FailingLLM, MockLLM
from support_ai import config
from support_ai.validator import validate


def _ticket(text: str = "не воспроизводится видео") -> SanitizedTicket:
    return SanitizedTicket(
        ticket_id="T-1",
        idempotency_key="web:T-1:1",
        channel="web",
        language="ru",
        redacted_text=text,
    )


def _policy(route: str = "AUTO_CANDIDATE") -> PolicyDecision:
    return PolicyDecision(
        route=route,  # type: ignore[arg-type]
        risk_level="LOW",
        risk_type=None,
        target_queue="general",
        policy_rule_id="AUTO-001",
        policy_version="test",
        reason="test",
    )


def _hit(**overrides: object) -> Hit:
    values = {
        "doc_id": "KB-TECH-125",
        "title": "Видео не воспроизводится",
        "snippet": "Перезапустите приложение.",
        "score": 0.8,
        "auto_allowed": True,
        "approval_status": "published",
        "owner": "support-content",
        "expires_at": "2099-12-01",
        "doc_topics": ["TECHNICAL"],
        "topic_match": True,
    }
    values.update(overrides)
    return Hit(**values)  # type: ignore[arg-type]


def _retrieval(hit: Hit | None = None) -> RetrievalResult:
    selected = hit or _hit()
    return RetrievalResult(
        hits=[selected],
        max_score=selected.score,
        index_version="test",
        query_topic="TECHNICAL",
        threshold_used=0.35,
    )


def test_llm_failure_falls_back_without_raising() -> None:
    draft = make_draft(_ticket(), _retrieval(), _policy(), FailingLLM())

    assert draft.degraded is True
    assert draft.llm_used is False
    assert draft.mode == "template"
    assert draft.citations == ["KB-TECH-125"]
    assert draft.text


def test_escalate_does_not_call_llm() -> None:
    class CountingLLM:
        name = "counter"

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, system: str, user: str, timeout_s: float) -> LLMResult:
            self.calls += 1
            return LLMResult(text="must not happen", provider="test", model="test")

    llm = CountingLLM()
    draft = make_draft(_ticket(), _retrieval(), _policy("ESCALATE"), llm)

    assert llm.calls == 0
    assert draft.mode == "none"
    assert draft.reason == "GENERATION_FORBIDDEN_BY_POLICY"


def test_mock_prompt_contains_only_redacted_ticket_text() -> None:
    llm = MockLLM()
    make_draft(_ticket("позвоните <PHONE_1>"), _retrieval(), _policy(), llm)

    assert llm.last_prompt is not None
    assert "<PHONE_1>" in llm.last_prompt
    assert "+79991234567" not in llm.last_prompt
    assert llm.last_result is not None


def test_validator_rejects_missing_citation() -> None:
    draft = Draft("Перезапустите приложение.", [], "template", False, False)

    result = validate(draft, _retrieval(), _policy(), _ticket())

    assert result.ok is False
    assert "MISSING_CITATION" in result.failed_checks


def test_validator_rejects_refund_promise() -> None:
    draft = Draft("Гарантируем, что вернём деньги.", ["KB-TECH-125"], "template", False, False)

    result = validate(draft, _retrieval(), _policy(), _ticket())

    assert result.ok is False
    assert "FORBIDDEN_PROMISE" in result.failed_checks


def test_validator_rejects_article_in_review() -> None:
    hit = _hit(approval_status="review")
    draft = Draft("Безопасный ответ.", [hit.doc_id], "template", False, False)

    result = validate(draft, _retrieval(hit), _policy(), _ticket())

    assert result.ok is False
    assert "ARTICLE_NOT_PUBLISHED" in result.failed_checks


def test_validator_rejects_expired_article() -> None:
    hit = _hit(expires_at="2020-01-01")
    draft = Draft("Безопасный ответ.", [hit.doc_id], "template", False, False)

    result = validate(draft, _retrieval(hit), _policy(), _ticket())

    assert result.ok is False
    assert "ARTICLE_EXPIRED" in result.failed_checks


def test_validator_rejects_low_relevance_for_auto() -> None:
    hit = _hit(score=config.AUTO_RELEVANCE_THRESHOLD - 0.001)
    draft = Draft("Безопасный ответ.", [hit.doc_id], "template", False, False)

    result = validate(draft, _retrieval(hit), _policy(), _ticket())

    assert result.ok is False
    assert "LOW_RELEVANCE_FOR_AUTO" in result.failed_checks


def test_validator_accepts_auto_relevance_at_boundary() -> None:
    hit = _hit(score=config.AUTO_RELEVANCE_THRESHOLD)
    draft = Draft("Безопасный ответ.", [hit.doc_id], "template", False, False)

    result = validate(draft, _retrieval(hit), _policy(), _ticket())

    assert "LOW_RELEVANCE_FOR_AUTO" not in result.failed_checks


def test_validator_rejects_low_answerability_for_auto() -> None:
    hit = _hit(
        title="Как изменить язык интерфейса",
        snippet="Откройте профиль, выберите язык и сохраните изменения.",
    )
    draft = Draft("Безопасный ответ.", [hit.doc_id], "template", False, False)

    result = validate(
        draft,
        _retrieval(hit),
        _policy(),
        _ticket("как изменить номер телефона в профиле"),
    )

    assert result.ok is False
    assert "LOW_ANSWERABILITY_FOR_AUTO" in result.failed_checks


def test_validator_normalizes_word_forms_for_answerability() -> None:
    hit = _hit(
        title="Фотография в профиле",
        snippet="Загрузите фотографию профиля и сохраните изменения.",
    )
    draft = Draft("Безопасный ответ.", [hit.doc_id], "template", False, False)

    result = validate(
        draft,
        _retrieval(hit),
        _policy(),
        _ticket("фотографию профиля"),
    )

    assert "LOW_ANSWERABILITY_FOR_AUTO" not in result.failed_checks
