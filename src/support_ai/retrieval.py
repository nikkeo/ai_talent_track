"""Поиск по базе знаний. Владелец: Agent B, блок 1.

Заглушка возвращает пустой результат, чтобы pipeline Agent A корректно
деградировал в ESCALATE / NO_RELIABLE_CONTEXT ещё до реализации.
"""

from . import config
from .contracts import RetrievalResult


def search(query: str, topic: str | None, k: int = config.RETRIEVAL_TOP_K) -> RetrievalResult:
    """TF-IDF по KB, мягкий буст по теме. Порог релевантности применяет pipeline, не retrieval."""
    return RetrievalResult(hits=[], max_score=0.0, index_version=config.VERSIONS["kb_index"])
