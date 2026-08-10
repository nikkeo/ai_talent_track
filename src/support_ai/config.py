"""Единственное место с порогами и версиями. Менять только через Lead."""

import hashlib
from pathlib import Path

# Выбран свипом по стоимости решений, см. docs/eval_report.md.
# Оговорка: на eval-наборе из 20 примеров стоимость равна нулю для 0.30 и 0.35,
# то есть выбор слабо идентифицирован — при первых реальных данных пересчитать.
CONF_THRESHOLD = 0.30
RELEVANCE_THRESHOLD = 0.35

# Тема лишь допускает автоответ. Окончательное право даёт article.auto_allowed
# в связке с policy и порогами AUTO_* ниже.
AUTO_ALLOWLIST = {"HOWTO", "STATUS", "TECHNICAL"}

# Порог понимания и порог права на действие — разные величины.
# Уверенности 0.31 достаточно, чтобы сказать «это HOWTO», и недостаточно,
# чтобы ответить пользователю без человека. Независимый тестер показал оба
# пробоя: перефразированное списание прошло при confidence 0.312, а смыслово
# нерелевантная статья разрешила автоответ при relevance 0.374.
# Значения выбраны консервативно, выше обоих наблюдённых пробоев, и подлежат
# свипу по стоимости решений на первых реальных данных.
AUTO_CONF_THRESHOLD = 0.60        # право отвечать самому
AUTO_RELEVANCE_THRESHOLD = 0.50   # право отправлять, а не только показать оператору
MAX_TICKET_CHARS = 4096
MAX_ANSWER_CHARS = 1200      # единый лимит; per-channel — вопрос целевой архитектуры
LLM_TIMEOUT_S = 2.0
CB_FAILURES = 3
CB_COOLDOWN_S = 30.0
RETRIEVAL_TOP_K = 5
TOPIC_BOOST = 1.15

VERSIONS = {
    "classifier": "tfidf-lr-0.2",
    "policy": "2026.08.2",
    "kb_index": "kb-0.2",
    "prompt": "draft-v1",
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
KB_DIR = DATA_DIR / "kb"
DOCS_DIR = PROJECT_ROOT / "docs"
LOGS_DIR = PROJECT_ROOT / "logs"
AUDIT_PATH = LOGS_DIR / "audit_log.jsonl"

# Три непересекающихся набора: demo не участвует ни в обучении, ни в выборе порогов.
TRAIN_TICKETS = DATA_DIR / "tickets_train.jsonl"
EVAL_TICKETS = DATA_DIR / "tickets_eval.jsonl"
DEMO_TICKETS = DATA_DIR / "tickets_demo.jsonl"


def _sha8(path: Path) -> str:
    """Версия локального файла для воспроизводимости решений в audit."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:8]
    except OSError:
        return "missing"


def _dir_sha8(path: Path, pattern: str = "*.md") -> str:
    """Версия содержимого каталога: важно не число файлов, а их содержимое."""
    digest = hashlib.sha256()
    try:
        for item in sorted(path.glob(pattern)):
            digest.update(item.name.encode())
            digest.update(item.read_bytes())
    except OSError:
        return "missing"
    return digest.hexdigest()[:8]


def runtime_versions(llm_mode: str) -> dict:
    """Полный снимок версий для audit-события: почему два одинаковых тикета
    получили разные решения после правки KB, порогов или датасета."""
    return {
        **VERSIONS,
        "config": _sha8(Path(__file__)),
        "training_data": _sha8(TRAIN_TICKETS),
        # Ручные строки версий выше легко забыть поднять; хеши меняются сами.
        "policy_rules": _sha8(Path(__file__).with_name("policy.py")),
        "kb_content": _dir_sha8(KB_DIR),
        "llm_mode": llm_mode,
    }
