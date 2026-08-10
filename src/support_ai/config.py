"""Единственное место с порогами и версиями. Менять только через Lead."""

from pathlib import Path

CONF_THRESHOLD = 0.65
RELEVANCE_THRESHOLD = 0.35
AUTO_ALLOWLIST = {"HOWTO", "STATUS", "TECHNICAL"}   # темы, где возможен автоответ
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
SEED_TICKETS = DATA_DIR / "tickets_seed.jsonl"
DEMO_TICKETS = DATA_DIR / "tickets_demo.jsonl"
