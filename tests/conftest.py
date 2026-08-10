from __future__ import annotations

"""Общие фикстуры и помощники adversarial-набора.

Фикстуры pytest подхватывает автоматически, константы и функции тест-файлы
импортируют явно: from conftest import *
"""

"""Враждебные тесты, написанные от спецификации (BRIEF_C §2), а не от кода.

Единственный источник ожиданий — таблица решений:

| Условие                                     | Retrieval | Generation | Результат                        |
| High risk (SEC / PRIV / LEG / FIN)          | нет       | нет        | ESCALATE                         |
| Low confidence или UNKNOWN                  | нет       | нет        | ESCALATE                         |
| Safe, контекст не найден                    | да        | нет        | ESCALATE (NO_RELIABLE_CONTEXT)   |
| Safe, контекст есть, тема не в allowlist    | да        | да         | DRAFT_FOR_OPERATOR               |
| Safe, контекст есть, allowlist+auto_allowed | да        | да         | AUTO_RESPONSE                    |
| Validation failed                           | да        | да         | DRAFT_FOR_OPERATOR               |
| Audit failed                                | любое     | любое      | ESCALATE                         |

Право на AUTO_RESPONSE требует одновременно: route == AUTO_CANDIDATE, релевантный
источник, hit.auto_allowed, approval_status == "published", owner, заданный и не
истёкший expires_at, validation.ok, записанное audit-событие.

Работа только через публичный API: pipeline.process / route / fulfill.

Негативные кейсы снабжены проверкой контрольного (baseline) прохода: без неё тест
«автоответа не было» зеленеет по любой причине — например потому, что классификатор
и так не уверен, — и ничего не доказывает.
"""


import json
import re
import sys
import uuid
from datetime import date, datetime

import pytest

from support_ai import config, pipeline
from support_ai.contracts import Ticket
from support_ai.llm import MockLLM

ACTIONS = {"AUTO_RESPONSE", "DRAFT_FOR_OPERATOR", "ESCALATE"}
SEVERITY = {"AUTO_RESPONSE": 0, "DRAFT_FOR_OPERATOR": 1, "ESCALATE": 2}

# Безопасные тикеты-кандидаты на строку 5 таблицы: тема в allowlist, статья KB
# published / auto_allowed / owner задан / expires_at не истёк.
# Конкретная формулировка подбирается на старте: качество классификатора меняется
# от коммита к коммиту, а зашитый текст превратил бы негативные тесты в вырожденные.
AUTO_CANDIDATES = (
    "как изменить язык интерфейса",
    "не воспроизводится видео в приложении",
    "как скачать урок",
    "не работает звук в мобильном приложении",
    "не загружается видео в приложении",
    "где найти настройки языка",
)


# --------------------------------------------------------------------------- #
# помощники
# --------------------------------------------------------------------------- #


def make_ticket(text: str, *, key: str | None = None, channel: str = "mobile", **meta) -> Ticket:
    key = key or f"adv:{uuid.uuid4().hex}"
    return Ticket(
        ticket_id=f"ADV-{uuid.uuid4().hex[:8]}",
        customer_ref="adversarial",
        channel=channel,
        language="ru",
        text=text,
        created_at="2026-08-10T12:00:00Z",
        idempotency_key=key,
        metadata=dict(meta),
    )


def run(text: str, *, key: str | None = None, channel: str = "mobile", faults=frozenset(), **meta):
    """process() по тексту. Возвращает (Decision, AuditEvent)."""
    return pipeline.process(make_ticket(text, key=key, channel=channel, **meta), faults=frozenset(faults))


def digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def as_dict(obj) -> dict:
    """Поле аудита может быть dict или dataclass — приводим к dict."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    return dict(vars(obj))


def confidence_of(event) -> float | None:
    return as_dict(event.classification).get("confidence")


def topic_of(event) -> str | None:
    return as_dict(event.classification).get("topic")


def max_score_of(event) -> float | None:
    return as_dict(event.retrieval).get("max_score")


def hits_of(event) -> list[dict]:
    return [as_dict(h) for h in (as_dict(event.retrieval).get("hits") or [])]


@pytest.fixture
def audit_tail():
    """Возвращает функцию, читающую то, что дописано в audit_log.jsonl за время теста."""
    path = config.AUDIT_PATH
    start = path.stat().st_size if path.exists() else 0

    def read_raw() -> str:
        if not path.exists():
            return ""
        return path.read_bytes()[start:].decode("utf-8", "replace")

    def read_events() -> list[dict]:
        out = []
        for line in read_raw().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"_unparsed": line})
        return out

    read_raw.events = read_events  # type: ignore[attr-defined]
    return read_raw


@pytest.fixture
def prompt_spy(monkeypatch):
    """Перехватывает MockLLM.last_prompt — то, что реально ушло в модель."""
    captured: list[str] = []
    original = MockLLM.complete

    def spy(self, system, user, timeout_s):
        result = original(self, system, user, timeout_s)
        captured.append(f"{getattr(self, 'last_prompt', '')}\n{system}\n{user}")
        return result

    monkeypatch.setattr(MockLLM, "complete", spy)
    return captured


def _discover_auto_texts() -> list[str]:
    """Подбирает формулировки, которые реально проходят весь путь до AUTO_RESPONSE."""
    found = []
    for text in AUTO_CANDIDATES:
        try:
            decision, _ = pipeline.process(make_ticket(text))
        except Exception:  # noqa: BLE001 — на этапе сбора важен сам факт непригодности
            continue
        if decision.final_action == "AUTO_RESPONSE":
            found.append(text)
    return found


_AUTO_TEXTS = _discover_auto_texts()
AUTO_TEXT = _AUTO_TEXTS[0] if _AUTO_TEXTS else None
AUTO_TEXT_ALT = _AUTO_TEXTS[1] if len(_AUTO_TEXTS) > 1 else AUTO_TEXT

needs_auto_path = pytest.mark.skipif(
    AUTO_TEXT is None,
    reason=(
        "ни один безопасный тикет из allowlist не доходит до AUTO_RESPONSE — "
        f"проверено: {list(AUTO_CANDIDATES)}"
    ),
)


def _drop_kb_caches() -> None:
    """Сбрасывает мемоизированный индекс KB, чтобы подмена каталога была видна."""
    for module in list(sys.modules.values()):
        if not getattr(module, "__name__", "").startswith("support_ai"):
            continue
        for name in dir(module):
            attr = getattr(module, name, None)
            if hasattr(attr, "cache_clear"):
                attr.cache_clear()


@pytest.fixture
def custom_kb(monkeypatch, tmp_path):
    """Подменяет каталог KB на временный — иначе governance-кейсы нечем воспроизвести.

    Статья строится вокруг baseline-тикета, чтобы она гарантированно нашлась
    retrieval-ом: иначе тест «автоответа не будет» пройдёт просто из-за отсутствия
    контекста и ничего не докажет.
    """

    def install(body: str, **overrides: str) -> None:
        meta = {
            "document_id": "KB-CUSTOM-999",
            "title": AUTO_TEXT or "статья",
            "product": "mobile-app",
            "categories": "[HOWTO, TECHNICAL, STATUS]",
            "updated_at": "2026-07-01",
            "expires_at": "2027-07-01",
            "owner": "learning-content",
            "approval_status": "published",
            "auto_allowed": "true",
        }
        meta.update(overrides)
        front = "".join(f"{k}: {v}\n" for k, v in meta.items() if v is not None)
        (tmp_path / "article.md").write_text(f"---\n{front}---\n{body}", encoding="utf-8")
        monkeypatch.setattr(config, "KB_DIR", tmp_path)
        for module in list(sys.modules.values()):
            if getattr(module, "__name__", "").startswith("support_ai") and hasattr(module, "KB_DIR"):
                monkeypatch.setattr(module, "KB_DIR", tmp_path, raising=False)
        _drop_kb_caches()

    yield install
    _drop_kb_caches()


def kb_catalog() -> dict[str, dict]:
    """Метаданные статей KB из front matter — эталон governance для проверки цитат."""
    catalog: dict[str, dict] = {}
    for path in sorted(config.KB_DIR.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---"):
            continue
        meta: dict = {}
        for line in raw.split("---", 2)[1].splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
        if meta.get("document_id"):
            catalog[meta["document_id"]] = meta
    return catalog


def is_expired(meta: dict, today: date | None = None) -> bool:
    raw = meta.get("expires_at")
    if not raw:
        return True  # не задан → права на автоответ нет
    return datetime.strptime(raw[:10], "%Y-%m-%d").date() < (today or date.today())


def resolve_citation(citation: str, catalog: dict[str, dict]) -> dict | None:
    for doc_id, meta in catalog.items():
        if doc_id in citation:
            return meta
    for meta in catalog.values():
        if meta.get("title") and meta["title"] in citation:
            return meta
    return None
