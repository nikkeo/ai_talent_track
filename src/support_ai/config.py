"""Единственное место с порогами и версиями. Менять только через Lead."""

import hashlib
from pathlib import Path

CONF_THRESHOLD = 0.65
RELEVANCE_THRESHOLD = 0.35

# Тема лишь допускает автоответ. Окончательное право даёт article.auto_allowed
# в связке с policy — см. таблицу решений в DEV_PLAN §9.
AUTO_ALLOWLIST = {"HOWTO", "STATUS", "TECHNICAL"}
MAX_TICKET_CHARS = 4096
LLM_TIMEOUT_S = 2.0
CB_FAILURES = 3
CB_COOLDOWN_S = 30.0
RETRIEVAL_TOP_K = 5
TOPIC_BOOST = 1.15

VERSIONS = {
    "classifier": "tfidf-lr-0.1",
    "policy": "2026.08.1",
    "kb_index": "kb-0.1",
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


def runtime_versions(llm_mode: str) -> dict:
    """Полный снимок версий для audit-события: почему два одинаковых тикета
    получили разные решения после правки KB, порогов или датасета."""
    return {
        **VERSIONS,
        "config": _sha8(Path(__file__)),
        "training_data": _sha8(TRAIN_TICKETS),
        "llm_mode": llm_mode,
    }
