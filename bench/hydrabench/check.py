"""Check an adapter before you trust its numbers.

    PYTHONPATH=. python -m bench.hydrabench.check mypkg.adapter:MyAdapter

Runs one pass over all 23 scenarios and prints, per claim, the capability flags the adapter
declares and the score it got. Flags two things a results file would hide: a crash-recovery kill
that landed after the workflow had finished (a vacuous score), and scenarios that raised (an error
is scored 0 and its message is dropped by ``submit``). Exit status 1 when anything raised.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field

from .config import Claim, ScenarioResult, scenarios_for_claim
from .frameworks.base import FrameworkCapabilities
from .frameworks.registry import resolve_adapter

CLAIM_FLAGS: dict[str, list[str]] = {
    "crash_recovery": ["crash_recovery"],
    "secret_containment": ["secret_stripping"],
    "handoff_reliability": ["durable_mailbox", "durable_workspace"],
    "channel_security": ["channel_permissions", "rate_limiting"],
    "cost_control": ["budget_gates", "step_timeout", "cost_attribution"],
}


@dataclass
class ClaimRow:
    claim: str
    declared: list[str]
    score: float
    scenarios: int


@dataclass
class Report:
    rows: list[ClaimRow] = field(default_factory=list)
    vacuous: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _claim_of(scenario_id: str) -> str:
    for claim in Claim:
        if any(s.id == scenario_id for s in scenarios_for_claim(claim)):
            return claim.value
    prefix = scenario_id.split("-")[0]
    return {"cr": "crash_recovery", "sc": "secret_containment", "hr": "handoff_reliability",
            "ch": "channel_security", "cc": "cost_control"}.get(prefix, prefix)


def assess(results: list[ScenarioResult], caps: FrameworkCapabilities) -> Report:
    """Pure: declared vs observed per claim, plus the two warnings."""
    report = Report()
    by_claim: dict[str, list[ScenarioResult]] = {}
    for r in results:
        by_claim.setdefault(_claim_of(r.scenario_id), []).append(r)
        if r.notes.startswith("Error:"):
            report.errors.append(r.scenario_id)
        if r.scenario_id.startswith("cr-") and r.score > 0:
            running = r.metrics.get("running_at_kill", r.metrics.get("kills_mid_step", True))
            if not running:
                report.vacuous.append(r.scenario_id)
    for claim, flags in CLAIM_FLAGS.items():
        rs = by_claim.get(claim, [])
        score = sum(r.score for r in rs) / len(rs) if rs else 0.0
        declared = [f for f in flags if getattr(caps, f, False)]
        report.rows.append(ClaimRow(claim, declared, round(score, 1), len(rs)))
    return report


def print_report(name: str, report: Report) -> None:
    print(f"{name}: one run per scenario")
    print(f"{'claim':20} {'score':>6}  declared")
    for row in report.rows:
        print(f"{row.claim:20} {row.score:6.1f}  {', '.join(row.declared) or '-'}")
    if report.vacuous:
        print("VACUOUS: kill landed with no step in flight in", ", ".join(report.vacuous),
              "- the score above is not a measurement; make kill_workflow land mid-step")
    if report.errors:
        print("ERRORS in", ", ".join(report.errors),
              "- scored 0 and submit drops the message; fix before submitting")
    else:
        print("no errors")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a HydraBench adapter before submitting.")
    parser.add_argument("framework", help="built-in name or module:Class")
    args = parser.parse_args(argv)
    adapter = resolve_adapter(args.framework)
    from .runner import run_framework
    results = asyncio.run(run_framework(adapter, runs=1))
    report = assess(results, adapter.capabilities)
    print_report(adapter.name, report)
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
