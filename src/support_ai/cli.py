"""Offline command-line demonstration of routing and fulfillment boundaries."""

import argparse
import json
from datetime import UTC, datetime
from uuid import uuid4

from . import config
from .contracts import Ticket
from .pipeline import fulfill, route


def _tickets(args: argparse.Namespace) -> list[Ticket]:
    if args.demo:
        return [
            Ticket(**json.loads(line))
            for line in config.DEMO_TICKETS.read_text(encoding="utf-8").splitlines()
            if line
        ]
    ticket_id = f"cli-{uuid4().hex[:8]}"
    return [
        Ticket(
            ticket_id=ticket_id,
            customer_ref="cli",
            channel=args.channel,
            language="ru",
            text=args.text,
            created_at=datetime.now(UTC).isoformat(),
            idempotency_key=f"{args.channel}:{ticket_id}:v1",
        )
    ]


def _print_ticket(ticket: Ticket, *, llm_mode: str, faults: frozenset[str]) -> None:
    outcome = route(ticket, faults=faults)
    print(f"\n[{ticket.ticket_id}] {ticket.channel}")
    print(f"  topic: {outcome.classification.topic} ({outcome.classification.confidence:.3f})")
    print(f"  policy: {outcome.policy.policy_rule_id} -> {outcome.policy.route}")
    print(f"  sync_route_ms: {outcome.routing.sync_route_ms:.3f}")
    print("  ----- ASYNC FULFILLMENT BOUNDARY -----")
    decision, event = fulfill(outcome, llm_mode=llm_mode, faults=faults)
    hits = (event.retrieval or {}).get("hits", [])
    if hits:
        rendered = ", ".join(f"{hit['doc_id']}={hit['score']:.3f}" for hit in hits)
    else:
        rendered = "none (short-circuit or no reliable context)"
    print(f"  documents: {rendered}")
    print(f"  final_action: {decision.final_action}")
    print(f"  target_queue: {decision.target_queue}")
    print(f"  reason: {decision.reason}")
    print(f"  async_fulfill_ms: {decision.latency_ms['async_fulfill_ms']:.3f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline support ticket routing demo")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", action="store_true", help="run all six demo scenarios")
    source.add_argument("--text", help="process one ticket")
    parser.add_argument("--channel", choices=("chat", "email", "web", "mobile"), default="chat")
    parser.add_argument("--fail-llm", action="store_true")
    parser.add_argument("--fail-audit", action="store_true")
    parser.add_argument("--fail-policy", action="store_true")
    parser.add_argument("--fail-retrieval", action="store_true")
    args = parser.parse_args()

    faults = frozenset(
        name
        for name, enabled in (
            ("audit", args.fail_audit),
            ("policy", args.fail_policy),
            ("retrieval", args.fail_retrieval),
        )
        if enabled
    )
    for ticket in _tickets(args):
        # S3 демонстрирует локальный отказ LLM даже в обычном six-scenario demo.
        llm_mode = "fail" if args.fail_llm or (args.demo and ticket.ticket_id == "S3") else "mock"
        _print_ticket(ticket, llm_mode=llm_mode, faults=faults)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
