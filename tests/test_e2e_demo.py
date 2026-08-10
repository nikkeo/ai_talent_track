import json

from support_ai import config
from support_ai.contracts import Ticket
from support_ai.pipeline import process


def test_six_demo_scenarios_end_to_end(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "AUDIT_PATH", tmp_path / "audit.jsonl")
    expected = {
        "S1": ("AUTO_RESPONSE", "automation"),
        "S2": ("ESCALATE", "financial-support"),
        "S3": ("DRAFT_FOR_OPERATOR", "general"),
        "S4": ("ESCALATE", "general"),
        "S5": ("ESCALATE", "general"),
        "S6": ("ESCALATE", "financial-support"),
    }
    rows = [json.loads(line) for line in config.DEMO_TICKETS.read_text().splitlines()]

    actual = {}
    for row in rows:
        llm_mode = "fail" if row["ticket_id"] == "S3" else "mock"
        decision, _ = process(Ticket(**row), llm_mode=llm_mode)
        actual[row["ticket_id"]] = (decision.final_action, decision.target_queue)

    assert actual == expected
