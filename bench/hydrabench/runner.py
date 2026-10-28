"""HydraBench runner: orchestrates scenarios across frameworks."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from .config import RUNS_PER_SCENARIO, SCENARIOS, Claim, ScenarioResult, scenarios_for_claim
from .frameworks.base import FrameworkAdapter
from .metrics import BenchmarkResults, build_results, results_to_json, save_results
from .scenarios import (
    run_channel_security,
    run_cost_control,
    run_crash_recovery,
    run_handoff_reliability,
    run_secret_containment,
)

logger = logging.getLogger(__name__)

# Map claims to scenario runners
CLAIM_RUNNERS = {
    Claim.CRASH_RECOVERY: run_crash_recovery,
    Claim.SECRET_CONTAINMENT: run_secret_containment,
    Claim.HANDOFF_RELIABILITY: run_handoff_reliability,
    Claim.CHANNEL_SECURITY: run_channel_security,
    Claim.COST_CONTROL: run_cost_control,
}


async def run_framework(
    adapter: FrameworkAdapter,
    runs: int = RUNS_PER_SCENARIO,
    claims: list[Claim] | None = None,
) -> list[ScenarioResult]:
    """Run all scenarios for a single framework."""
    results: list[ScenarioResult] = []
    target_claims = claims or list(Claim)

    logger.info("Setting up %s", adapter.name)
    await adapter.setup()

    try:
        for claim in target_claims:
            runner = CLAIM_RUNNERS[claim]
            scenarios = scenarios_for_claim(claim)
            logger.info(
                "Running %d %s scenarios on %s",
                len(scenarios), claim.value, adapter.name,
            )

            for scenario in scenarios:
                for run_idx in range(runs):
                    try:
                        result = await runner(adapter, scenario, run_idx)
                        results.append(result)
                    except Exception as e:
                        logger.error(
                            "Scenario %s run %d failed on %s: %s",
                            scenario.id, run_idx, adapter.name, e,
                        )
                        results.append(ScenarioResult(
                            scenario_id=scenario.id,
                            framework=adapter.name,
                            run=run_idx,
                            metrics={},
                            score=0,
                            notes=f"Error: {e}",
                        ))
    finally:
        await adapter.teardown()

    return results


async def run_benchmark(
    adapters: list[FrameworkAdapter],
    runs: int = RUNS_PER_SCENARIO,
    claims: list[Claim] | None = None,
    output_path: Path | None = None,
) -> BenchmarkResults:
    """Run full benchmark across all frameworks."""
    all_results: list[ScenarioResult] = []

    start = time.monotonic()

    for adapter in adapters:
        fw_results = await run_framework(adapter, runs=runs, claims=claims)
        all_results.extend(fw_results)

    elapsed = time.monotonic() - start

    results = build_results(all_results, runs_per_scenario=runs)
    results.metadata["elapsed_seconds"] = round(elapsed, 2)

    if output_path:
        save_results(results, output_path)
        logger.info("Results saved to %s", output_path)

    return results


def print_leaderboard(results: BenchmarkResults) -> None:
    """Print a text leaderboard to stdout."""
    ranked = sorted(results.frameworks, key=lambda f: f.overall_score, reverse=True)

    print("\n" + "=" * 70)
    print("HydraBench Leaderboard")
    print("=" * 70)
    print(f"{'Rank':<6}{'Framework':<20}{'Score':<12}{'+-':<8}")
    print("-" * 70)

    for i, fw in enumerate(ranked, 1):
        print(f"{i:<6}{fw.name:<20}{fw.overall_score:<12.1f}{fw.overall_std:<8.1f}")

    print("-" * 70)
    print("\nPer-claim breakdown:")
    print(f"{'Framework':<20}", end="")
    for claim in Claim:
        label = claim.value.replace("_", " ").title()[:12]
        print(f"{label:<14}", end="")
    print()
    print("-" * 70)

    for fw in ranked:
        print(f"{fw.name:<20}", end="")
        for claim_summary in fw.claims:
            score = claim_summary.score_mean
            std = claim_summary.score_std
            print(f"{score:>5.1f}+-{std:<5.1f}  ", end="")
        print()

    print("=" * 70)
