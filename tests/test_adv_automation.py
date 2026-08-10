"""Adversarial: governance KB и поверхность автоматизации."""

import pytest  # noqa: F401

from conftest import *  # noqa: F401,F403
from conftest import _AUTO_TEXTS

# --------------------------------------------------------------------------- #
# §3 KB governance
# --------------------------------------------------------------------------- #


def test_auto_response_only_cites_fully_governed_articles():
    """Инвариант §2: автоответ — только на published / owner / auto_allowed / не истёкшую статью."""
    catalog = kb_catalog()
    corpus = [t for t in _AUTO_TEXTS] + [
        "нет звука во время урока",
        "не воспроизводится видео в приложении",
        "жду когда завершатся плановые технические работы",
        "не приходит подтверждение входа с нового устройства",
        "забыл пароль, как восстановить",
        "как скачать материалы курса",
    ]
    corpus += [
        json.loads(line)["text"]
        for line in config.DEMO_TICKETS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    auto_seen, violations = 0, []
    for text in corpus:
        decision, _ = run(text)
        if decision.final_action != "AUTO_RESPONSE":
            continue
        auto_seen += 1
        if not decision.citations:
            violations.append((text[:40], "автоответ без цитат"))
            continue
        for citation in decision.citations:
            meta = resolve_citation(citation, catalog)
            if meta is None:
                violations.append((text[:40], f"цитата не сопоставима со статьёй KB: {citation!r}"))
                continue
            doc = meta.get("document_id")
            if meta.get("approval_status") != "published":
                violations.append((text[:40], f"{doc} approval={meta.get('approval_status')}"))
            if str(meta.get("auto_allowed")).lower() != "true":
                violations.append((text[:40], f"{doc} auto_allowed={meta.get('auto_allowed')}"))
            if not meta.get("owner"):
                violations.append((text[:40], f"{doc} без owner"))
            if is_expired(meta):
                violations.append((text[:40], f"{doc} expires_at={meta.get('expires_at')}"))
    assert auto_seen, "в корпусе не оказалось ни одного автоответа — инвариант не проверен"
    assert not violations, f"автоответ на негодной статье: {violations}"


def test_expired_article_cannot_produce_auto_response():
    """KB-STATUS-301: auto_allowed true, published, owner есть, но expires_at 2026-08-09 — истёк."""
    text = "жду когда завершатся плановые технические работы"
    decision, event = run(text)
    top = [h.get("doc_id") for h in hits_of(event)][:1]
    if top != ["KB-STATUS-301"]:
        pytest.skip(f"истёкшая статья не стала топ-хитом: {top}")
    assert decision.final_action != "AUTO_RESPONSE", (
        f"автоответ по истёкшей статье: citations={decision.citations} reason={decision.reason}"
    )


def test_article_in_review_cannot_produce_auto_response():
    """KB-ACCOUNT-417: approval_status=review — автоответа быть не может."""
    decision, _ = run("не приходит подтверждение входа с нового устройства на почту")
    assert not (
        decision.final_action == "AUTO_RESPONSE" and any("KB-ACCOUNT-417" in c for c in decision.citations)
    ), f"автоответ по статье в статусе review: {decision.citations}"


@needs_auto_path
def test_published_article_without_owner_cannot_auto_answer(custom_kb):
    """published + auto_allowed, но owner не задан — права на автоответ нет."""
    custom_kb(
        f"{AUTO_TEXT}: откройте раздел и следуйте подсказке на экране.\n",
        document_id="KB-NOOWNER-998",
        owner=None,
    )
    decision, event = run(AUTO_TEXT)
    if not any(h.get("doc_id") == "KB-NOOWNER-998" for h in hits_of(event)):
        pytest.skip("подменённый KB не подхватился retrieval — кейс не воспроизводим")
    assert decision.final_action != "AUTO_RESPONSE", (
        f"автоответ по статье без owner: reason={decision.reason}"
    )


@needs_auto_path
def test_review_article_with_high_score_cannot_auto_answer(custom_kb):
    """approval_status=review при высоком score — автоответа быть не может."""
    custom_kb(
        f"{AUTO_TEXT}: откройте раздел и следуйте подсказке на экране.\n",
        document_id="KB-REVIEW-997",
        approval_status="review",
    )
    decision, event = run(AUTO_TEXT)
    if not any(h.get("doc_id") == "KB-REVIEW-997" for h in hits_of(event)):
        pytest.skip("подменённый KB не подхватился retrieval — кейс не воспроизводим")
    assert decision.final_action != "AUTO_RESPONSE", (
        f"автоответ по статье в review при score={max_score_of(event)}: reason={decision.reason}"
    )


# --------------------------------------------------------------------------- #
# Пятый прогон: реальная поверхность атаки после расширения KB до 27 статей
# --------------------------------------------------------------------------- #


def test_postfix_demo_s1_remains_auto_response():
    """Постфикс-инвариант: канонический S1 не должен потерять автоматизацию."""
    rows = [
        json.loads(line)
        for line in config.DEMO_TICKETS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    source = next(row for row in rows if row["ticket_id"] == "S1")
    ticket_data = dict(source)
    ticket_data["idempotency_key"] = f"{source['idempotency_key']}:postfix:{uuid.uuid4().hex}"
    decision, event = pipeline.process(Ticket(**ticket_data))

    assert decision.final_action == "AUTO_RESPONSE", (
        f"S1 регрессировал: {decision.final_action}/{decision.reason}; "
        f"topic={topic_of(event)} conf={confidence_of(event)} "
        f"score={max_score_of(event)} citations={decision.citations}"
    )
    assert decision.citations == ["KB-TECH-125"], decision
    assert decision.answer_text, "S1 получил AUTO_RESPONSE без ответа"


def test_semantically_irrelevant_kb_hit_cannot_authorize_auto_response():
    """Высокий lexical score не доказывает, что статья отвечает на вопрос.

    Контрольный запрос действительно относится к KB-HOWTO-214 и проходит весь
    auto-path. Враждебный запрос сохраняет общую HOWTO-форму, но спрашивает про
    номер телефона, а не про язык интерфейса.
    """
    baseline, baseline_event = run("как изменить язык интерфейса")
    assert baseline.final_action == "AUTO_RESPONSE", (
        f"baseline сломан: {baseline.final_action}/{baseline.reason}"
    )
    assert baseline.citations == ["KB-HOWTO-214"], (
        f"baseline нашёл не статью про язык: {baseline.citations}, "
        f"score={max_score_of(baseline_event)}"
    )

    text = "как изменить номер телефона в профиле"
    decision, event = run(text)
    assert decision.final_action == "DRAFT_FOR_OPERATOR", (
        "смыслово нерелевантная статья не перешла в безопасный операторский draft: "
        f"topic={topic_of(event)} conf={confidence_of(event)} "
        f"score={max_score_of(event)} citations={decision.citations} "
        f"answer={decision.answer_text!r}"
    )
    assert "LOW_RELEVANCE_FOR_AUTO" in decision.reason, decision
    assert decision.citations == ["KB-HOWTO-214"], decision


def test_word_coverage_boundary_loses_short_negation():
    """Characterization: word overlap не понимает отрицание «не».

    Значимые слова и lexical score совпадают со статьёй о смене языка, но запрос
    спрашивает, как избежать случайной смены. Если система всё ещё автоматизирует
    этот контрпример, фиксируем честное ограничение heuristic через XFAIL; когда
    появится semantic/intent gate, тот же тест станет обычным PASS.
    """
    baseline, _ = run("как изменить язык интерфейса")
    assert baseline.final_action == "AUTO_RESPONSE", (
        f"baseline сломан: {baseline.final_action}/{baseline.reason}"
    )

    text = "как не изменить язык интерфейса случайно"
    decision, event = run(text)
    hits = hits_of(event)
    assert topic_of(event) == "HOWTO", as_dict(event.classification)
    assert confidence_of(event) is not None and confidence_of(event) >= config.AUTO_CONF_THRESHOLD
    assert max_score_of(event) is not None and max_score_of(event) >= config.AUTO_RELEVANCE_THRESHOLD
    assert hits and hits[0].get("doc_id") == "KB-HOWTO-214", hits
    assert decision.citations == ["KB-HOWTO-214"], decision

    # После появления answerability coverage контрпример обязан проходить и его
    # порог; иначе это был бы другой short-circuit, а не граница word-overlap.
    from support_ai import validator

    coverage_fn = getattr(validator, "_answerability_coverage", None)
    if coverage_fn is not None:
        source = f"{hits[0].get('title', '')} {hits[0].get('snippet', '')}"
        coverage = coverage_fn(text, source)
        assert coverage >= config.AUTO_ANSWERABILITY_THRESHOLD, coverage

    if decision.final_action == "AUTO_RESPONSE":
        pytest.xfail(
            "документированное ограничение word coverage: короткое отрицание «не» "
            "теряется, хотя статья отвечает на противоположный вопрос"
        )
    assert decision.final_action != "AUTO_RESPONSE", decision


def test_paraphrased_duplicate_bank_operation_escalates_despite_safe_tail():
    """Две операции за один курс — PAYMENT risk вне текущей лексики FIN-001.

    В KB уже есть отдельная статья KB-PAY-514. Контроль с известной policy
    формулировкой подтверждает, что high-risk путь активен; HOWTO-хвост не должен
    позволять классификатору и retrieval понизить риск до автоответа.
    """
    catalog = kb_catalog()
    payment_article = catalog.get("KB-PAY-514")
    assert payment_article is not None, "в KB нет статьи о дублирующейся оплате KB-PAY-514"
    assert "PAYMENT" in payment_article.get("categories", ""), payment_article
    assert str(payment_article.get("auto_allowed")).lower() == "false", payment_article

    baseline = pipeline.route(
        make_ticket("оплата курса продублировалась в истории, как скачать урок")
    )
    assert (
        baseline.policy.route,
        baseline.policy.risk_type,
        baseline.policy.policy_rule_id,
    ) == ("ESCALATE", "FINANCIAL", "FIN-001"), (
        "baseline с известной финансовой лексикой не включил FIN-001: "
        f"{baseline.policy}"
    )

    text = "за один курс в банковской истории теперь две одинаковые операции, как скачать урок"
    decision, event = run(text)
    policy_data = as_dict(event.policy)
    assert decision.final_action == "ESCALATE" and policy_data.get("risk_type") == "FINANCIAL", (
        "перефразированная дублирующаяся банковская операция не распознана как high-risk: "
        f"topic={topic_of(event)} conf={confidence_of(event)} "
        f"policy={policy_data.get('policy_rule_id')}/{policy_data.get('risk_type')} "
        f"action={decision.final_action} score={max_score_of(event)} "
        f"citations={decision.citations} answer={decision.answer_text!r}"
    )


def test_meaningful_out_of_distribution_ticket_takes_low_001_path():
    """UNKNOWN/LOW-001 проверяется вне development-набора явным OOD-входом."""
    baseline, _ = run("как изменить язык интерфейса")
    assert baseline.final_action == "AUTO_RESPONSE", (
        f"baseline сломан: auto-path недоступен ({baseline.final_action}/{baseline.reason})"
    )

    text = "поддерживается ли экспорт заметок в obsidian"
    decision, event = run(text)
    classification = as_dict(event.classification)
    policy_data = as_dict(event.policy)
    assert classification.get("topic") == "UNKNOWN", classification
    assert classification.get("confidence", 1.0) < config.CONF_THRESHOLD, classification
    assert policy_data.get("policy_rule_id") == "LOW-001", policy_data
    assert policy_data.get("route") == "ESCALATE", policy_data
    assert decision.final_action == "ESCALATE", decision
    assert decision.target_queue == "general", decision
    assert decision.answer_text is None and decision.citations == [], decision
    assert not hits_of(event), "LOW-001 не должен запускать retrieval"


def test_entire_kb_catalog_satisfies_governance_invariants():
    """Все статьи валидны; intentional negative fixtures блокирует validator.

    Для review/expired статей сначала доказываем, что документ реально находится
    выше relevance-порога. Затем тем же Hit изолируем один governance-gate:
    контроль со всеми разрешающими метаданными проходит validation, а вариант с
    фактическим approval_status/expires_at — нет. Поэтому зелёный результат не
    может быть следствием classifier/policy/retrieval short-circuit.
    """
    from dataclasses import replace

    from support_ai import retrieval, validator
    from support_ai.contracts import Draft, PolicyDecision, RetrievalResult, SanitizedTicket

    paths = sorted(config.KB_DIR.glob("*.md"))
    catalog = kb_catalog()
    assert len(paths) == 27, f"ожидалось 27 markdown-статей KB, найдено {len(paths)}"
    assert len(catalog) == len(paths), (
        "не у каждой статьи есть уникальный document_id: "
        f"файлов={len(paths)}, document_id={len(catalog)}"
    )

    today = date.today()
    non_published: set[str] = set()
    expired: set[str] = set()
    violations: list[str] = []
    categories_by_doc: dict[str, set[str]] = {}
    for doc_id, meta in sorted(catalog.items()):
        categories = {
            item.strip()
            for item in meta.get("categories", "").strip("[]").split(",")
            if item.strip()
        }
        categories_by_doc[doc_id] = categories
        if meta.get("approval_status") != "published":
            non_published.add(doc_id)
        if not meta.get("owner"):
            violations.append(f"{doc_id}: owner отсутствует")
        expires_at = meta.get("expires_at")
        if not expires_at:
            violations.append(f"{doc_id}: expires_at отсутствует")
        else:
            try:
                if datetime.strptime(expires_at[:10], "%Y-%m-%d").date() < today:
                    expired.add(doc_id)
            except ValueError:
                violations.append(f"{doc_id}: expires_at={expires_at!r} невалиден")

        if str(meta.get("auto_allowed")).lower() not in {"true", "false"}:
            violations.append(f"{doc_id}: auto_allowed={meta.get('auto_allowed')!r} невалиден")

    assert non_published == {"KB-ACCOUNT-417"}, (
        f"неожиданный набор непубликованных статей: {sorted(non_published)}"
    )
    assert expired == {"KB-STATUS-301"}, (
        f"неожиданный набор просроченных статей: {sorted(expired)}"
    )

    high_risk_topics = {"PAYMENT", "REFUND", "FINANCIAL", "SECURITY", "PRIVACY", "LEGAL"}
    for doc_id, meta in sorted(catalog.items()):
        if categories_by_doc[doc_id] & high_risk_topics and str(meta.get("auto_allowed")).lower() == "true":
            violations.append(
                f"{doc_id}: high-risk categories={sorted(categories_by_doc[doc_id])} "
                "auto_allowed=true"
            )
        if doc_id not in non_published and meta.get("approval_status") != "published":
            violations.append(f"{doc_id}: approval_status={meta.get('approval_status')!r}")
        if doc_id not in expired and is_expired(meta, today):
            violations.append(f"{doc_id}: expires_at={meta.get('expires_at')} истёк на {today}")

    assert not violations, "нарушения governance в каталоге KB:\n" + "\n".join(violations)

    auto_policy = PolicyDecision(
        route="AUTO_CANDIDATE",
        risk_level="LOW",
        risk_type=None,
        target_queue="automation",
        policy_rule_id="AUTO-001",
        policy_version=config.VERSIONS["policy"],
        reason="AUTO_ALLOWED_TOPIC",
    )

    def assert_validator_gate(doc_id: str, failed_check: str) -> None:
        meta = catalog[doc_id]
        topics = sorted(categories_by_doc[doc_id])
        result = retrieval.search(meta["title"], topics[0] if topics else None, k=5)
        assert result.hits and result.hits[0].doc_id == doc_id, (
            f"{doc_id}: fixture не стала top retrieval hit: "
            f"{[(hit.doc_id, hit.score) for hit in result.hits]}"
        )
        assert result.max_score >= config.RELEVANCE_THRESHOLD, (
            f"{doc_id}: score={result.max_score} ниже {config.RELEVANCE_THRESHOLD}; "
            "validator gate недостижим"
        )

        actual_hit = result.hits[0]
        permissive_hit = replace(
            actual_hit,
            auto_allowed=True,
            approval_status="published",
            owner=actual_hit.owner or "governance-baseline",
            expires_at="2999-12-31",
        )
        baseline_retrieval = RetrievalResult(
            hits=[permissive_hit],
            max_score=actual_hit.score,
            index_version=result.index_version,
            query_topic=result.query_topic,
            threshold_used=result.threshold_used,
        )
        draft = Draft(
            text="Безопасный ответ по найденной статье.",
            citations=[doc_id],
            mode="template",
            llm_used=False,
            degraded=False,
        )
        ticket = SanitizedTicket(
            ticket_id=f"governance-{doc_id}",
            idempotency_key=f"governance:{doc_id}",
            channel="web",
            language="ru",
            redacted_text=meta["title"],
        )
        baseline = validator.validate(draft, baseline_retrieval, auto_policy, ticket)
        assert baseline.ok, f"{doc_id}: разрешающий baseline не прошёл: {baseline.failed_checks}"

        negative_hit = (
            replace(permissive_hit, approval_status=actual_hit.approval_status)
            if failed_check == "ARTICLE_NOT_PUBLISHED"
            else replace(permissive_hit, expires_at=actual_hit.expires_at)
        )
        negative_retrieval = replace(baseline_retrieval, hits=[negative_hit])
        negative = validator.validate(draft, negative_retrieval, auto_policy, ticket)
        assert not negative.ok and failed_check in negative.failed_checks, (
            f"{doc_id}: validator не закрыл {failed_check}: {negative.failed_checks}"
        )

    for doc_id in sorted(non_published):
        assert_validator_gate(doc_id, "ARTICLE_NOT_PUBLISHED")
    for doc_id in sorted(expired):
        assert_validator_gate(doc_id, "ARTICLE_EXPIRED")


def test_source_selection_is_deterministic_across_twenty_independent_runs():
    """Близкие score не должны менять citation между независимыми обработками."""
    text = "Как прикрепить документ к заданию или Где посмотреть результат и состояние модерации"
    citations: list[tuple[str, ...]] = []
    top_docs: list[str | None] = []
    score_pairs: list[tuple[float, float]] = []
    actions: list[str] = []

    for _ in range(20):
        decision, event = run(text, key=f"adv:determinism:{uuid.uuid4().hex}")
        hits = hits_of(event)
        assert len(hits) >= 2, f"ожидались два конкурирующих источника: {hits}"
        actions.append(decision.final_action)
        citations.append(tuple(decision.citations))
        top_docs.append(hits[0].get("doc_id"))
        score_pairs.append((hits[0]["score"], hits[1]["score"]))

    assert max(first - second for first, second in score_pairs) < 0.01, (
        f"кандидаты больше не близки по score: {score_pairs[0]}"
    )
    assert len(set(top_docs)) == 1, f"top document меняется: {top_docs}"
    assert len(set(citations)) == 1, f"citations меняются между повторами: {citations}"
    assert len(set(actions)) == 1, f"действие меняется между повторами: {actions}"
