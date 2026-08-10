"""Проверка ответа перед отправкой."""

from datetime import date
import re

from . import config
from .contracts import Draft, PolicyDecision, RetrievalResult, SanitizedTicket, Validation


_PLACEHOLDER_RE = re.compile(r"<[A-Z][A-Z0-9_]*_\d+>")
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+7|8)[\s()-]*\d{3}[\s()-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)")
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)")
_PROMISE_RE = re.compile(
    r"\b(?:верн(?:ём|ем|у)\s+деньги|гарантир(?:уем|ую)|компенсир(?:уем|ую)|возврат\s+одобрен|заявка\s+одобрен|"
    r"в\s+течение\s+\d+\s*(?:час(?:а|ов)?|дн(?:я|ей)))\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[a-zа-яё]+", re.IGNORECASE)
_RU_SUFFIXES = tuple(sorted(
    (
        "иями", "ами", "ями", "ого", "ему", "ому", "ыми", "ими",
        "аться", "яться", "иться", "ется", "ится", "ются", "утся",
        "ить", "ать", "ять", "еть", "ого", "его", "ому", "ему",
        "ий", "ый", "ой", "ая", "яя", "ое", "ее", "ые", "ие",
        "ую", "юю", "ов", "ев", "ам", "ям", "ах", "ях", "ом",
        "ем", "ия", "ию", "ью", "а", "я", "ы", "и", "у", "ю",
        "е", "о", "ь", "ти",
    ),
    key=len,
    reverse=True,
))


def _normalized_terms(text: str) -> set[str]:
    """Грубые нормализованные формы значимых слов, без внешней морфологии."""
    terms: set[str] = set()
    for raw in _WORD_RE.findall(text.casefold().replace("ё", "е")):
        if len(raw) < 4:
            continue
        term = raw
        for suffix in _RU_SUFFIXES:
            if term.endswith(suffix) and len(term) - len(suffix) >= 4:
                term = term[:-len(suffix)]
                break
        terms.add(term)
    return terms


def _answerability_coverage(query: str, source: str) -> float:
    query_terms = _normalized_terms(query)
    if not query_terms:
        return 0.0
    source_terms = _normalized_terms(source)
    return len(query_terms & source_terms) / len(query_terms)


def validate(
    draft: Draft,
    retrieval: RetrievalResult,
    policy: PolicyDecision,
    ticket: SanitizedTicket,
) -> Validation:
    """Право на автоответ проверяется здесь и только здесь.

    Требуется одновременно: policy.route == AUTO_CANDIDATE, citation на реально
    найденный документ, retrieval.max_score не ниже порога автоответа и
    достаточное покрытие значимых слов запроса процитированным источником,
    hit.auto_allowed, approval_status == "published",
    заданный owner, заданный и не истёкший expires_at, отсутствие PII и
    плейсхолдеров в тексте, отсутствие запрещённых обещаний, длина не выше
    config.MAX_ANSWER_CHARS.

    Лимит длины единый для всех каналов: channel сюда не передаётся, обещать
    per-channel проверку было бы невыполнимо. Разные лимиты по каналам —
    вопрос целевой архитектуры, не PoC.
    """
    failed: list[str] = []
    text = draft.text or ""
    hits_by_id = {hit.doc_id: hit for hit in retrieval.hits}

    if policy.route != "AUTO_CANDIDATE":
        failed.append("POLICY_NOT_AUTO_CANDIDATE")
    elif retrieval.max_score < config.AUTO_RELEVANCE_THRESHOLD:
        failed.append("LOW_RELEVANCE_FOR_AUTO")
    if not text:
        failed.append("EMPTY_DRAFT")
    if not draft.citations:
        failed.append("MISSING_CITATION")

    cited_hits = []
    for citation in draft.citations:
        hit = hits_by_id.get(citation)
        if hit is None:
            failed.append("CITATION_NOT_RETRIEVED")
        else:
            cited_hits.append(hit)

    if policy.route == "AUTO_CANDIDATE":
        cited_source = " ".join(f"{hit.title} {hit.snippet}" for hit in cited_hits)
        coverage = _answerability_coverage(ticket.redacted_text, cited_source)
        if coverage < config.AUTO_ANSWERABILITY_THRESHOLD:
            failed.append("LOW_ANSWERABILITY_FOR_AUTO")

    for hit in cited_hits:
        if not hit.auto_allowed:
            failed.append("ARTICLE_NOT_AUTO_ALLOWED")
        if hit.approval_status != "published":
            failed.append("ARTICLE_NOT_PUBLISHED")
        if not hit.owner:
            failed.append("ARTICLE_OWNER_MISSING")
        if not hit.expires_at:
            failed.append("ARTICLE_EXPIRY_MISSING")
        else:
            try:
                if date.fromisoformat(hit.expires_at) < date.today():
                    failed.append("ARTICLE_EXPIRED")
            except ValueError:
                failed.append("ARTICLE_EXPIRY_INVALID")

    if _PLACEHOLDER_RE.search(text):
        failed.append("PII_PLACEHOLDER_PRESENT")
    if any(pattern.search(text) for pattern in (_EMAIL_RE, _PHONE_RE, _CARD_RE)):
        failed.append("PII_PRESENT")
    if _PROMISE_RE.search(text):
        failed.append("FORBIDDEN_PROMISE")
    if len(text) > config.MAX_ANSWER_CHARS:
        failed.append("ANSWER_TOO_LONG")

    # Один код на тип сбоя, даже если несколько citations нарушают одно правило.
    unique_failed = list(dict.fromkeys(failed))
    return Validation(ok=not unique_failed, failed_checks=unique_failed)
