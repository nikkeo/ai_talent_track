"""Журнал автоматических решений. Нет записи — нет автодействия. Владелец: Agent A, блок 2."""

import json
from dataclasses import asdict
from threading import Lock

from . import config
from .contracts import AuditEvent


_write_lock = Lock()


def write(event: AuditEvent) -> bool:
    """Append JSONL в config.AUDIT_PATH. При ошибке возвращает False, не бросает исключение."""
    try:
        payload = json.dumps(asdict(event), ensure_ascii=False, separators=(",", ":"))
        config.AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _write_lock, config.AUDIT_PATH.open("a", encoding="utf-8") as stream:
            stream.write(payload + "\n")
            stream.flush()
        return True
    except (OSError, TypeError, ValueError):
        return False
