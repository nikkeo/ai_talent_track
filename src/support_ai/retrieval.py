"""Локальный TF-IDF поиск по опубликованной и черновой базе знаний."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from . import config
from .contracts import Hit, RetrievalResult


@dataclass(frozen=True)
class _Article:
    doc_id: str
    title: str
    body: str
    topics: list[str]
    auto_allowed: bool
    approval_status: str
    owner: str | None
    expires_at: str | None


def _frontmatter(path: Path) -> _Article:
    raw = path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    metadata: dict[str, str] = {}
    body = raw
    if len(parts) == 3 and not parts[0].strip():
        body = parts[2].strip()
        for line in parts[1].splitlines():
            key, separator, value = line.partition(":")
            if separator:
                metadata[key.strip()] = value.strip()

    categories = metadata.get("categories", "")
    topics = [item.strip() for item in categories.strip("[]").split(",") if item.strip()]
    return _Article(
        doc_id=metadata.get("document_id", path.stem),
        title=metadata.get("title", path.stem),
        body=body,
        topics=topics,
        auto_allowed=metadata.get("auto_allowed", "false").lower() == "true",
        approval_status=metadata.get("approval_status", "draft"),
        owner=metadata.get("owner") or None,
        expires_at=metadata.get("expires_at") or None,
    )


@lru_cache(maxsize=1)
def _index() -> tuple[list[_Article], TfidfVectorizer, object]:
    articles = [_frontmatter(path) for path in sorted(config.KB_DIR.glob("*.md"))]
    vectorizer = TfidfVectorizer(
        lowercase=True,
        token_pattern=r"(?u)\b\w\w+\b",
        ngram_range=(1, 2),
        sublinear_tf=True,
    )
    # Повтор заголовка — прозрачный и воспроизводимый способ повысить его вес.
    corpus = [f"{article.title} {article.title} {article.title} {article.body}" for article in articles]
    matrix = vectorizer.fit_transform(corpus) if corpus else None
    return articles, vectorizer, matrix


def _snippet(body: str, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", body).strip()
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def search(query: str, topic: str | None, k: int = config.RETRIEVAL_TOP_K) -> RetrievalResult:
    """TF-IDF по KB, мягкий буст по теме. Порог релевантности применяет pipeline, не retrieval."""
    articles, vectorizer, matrix = _index()
    if not articles or not query.strip() or k <= 0:
        return RetrievalResult(
            hits=[], max_score=0.0, index_version=config.VERSIONS["kb_index"],
            query_topic=topic, threshold_used=config.RELEVANCE_THRESHOLD,
        )

    scores = cosine_similarity(vectorizer.transform([query]), matrix).ravel()
    ranked: list[tuple[float, float, int, bool]] = []
    for index, article in enumerate(articles):
        topic_match = bool(topic and topic in article.topics)
        boosted = float(scores[index]) * (config.TOPIC_BOOST if topic_match else 1.0)
        ranked.append((boosted, float(scores[index]), index, topic_match))
    ranked.sort(key=lambda item: (-item[0], articles[item[2]].doc_id))

    hits = []
    for boosted, _raw, index, topic_match in ranked[: min(k, len(ranked))]:
        article = articles[index]
        hits.append(Hit(
            doc_id=article.doc_id,
            title=article.title,
            snippet=_snippet(article.body),
            score=boosted,
            auto_allowed=article.auto_allowed,
            approval_status=article.approval_status,  # type: ignore[arg-type]
            owner=article.owner,
            expires_at=article.expires_at,
            doc_topics=article.topics,
            topic_match=topic_match,
        ))
    return RetrievalResult(
        hits=hits,
        max_score=hits[0].score if hits else 0.0,
        index_version=config.VERSIONS["kb_index"],
        query_topic=topic,
        threshold_used=config.RELEVANCE_THRESHOLD,
    )
