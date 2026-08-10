"""Позволяет запускать pytest и CLI без установки пакета. Владелец: Lead, заморожен."""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# В _workspace живут git-worktree параллельных агентов со своими conftest.py.
# Без этого pytest подхватывает их тесты и подменяет sys.path чужим src.
collect_ignore_glob = ["_workspace/*", ".venv/*"]
