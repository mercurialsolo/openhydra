"""Metric collection, aggregation, and statistical analysis."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import CLAIM_WEIGHTS, SCENARIOS, Claim, ScenarioResult, scenarios_for_claim


@dataclass
class AggregatedMetric:
    """Statistical summary of a metric across runs."""
    mean: float
    std: float
    min: float
    max: float
    values: list[float]


@dataclass
class ScenarioSummary:
    """Aggregated results for one scenario across all runs."""
    scenario_id: str
    scenario_name: str
    claim: str
    framework: str
    score_mean: float
    score_std: float
    metrics: dict[str, AggregatedMetric]
    notes: str = ""


@dataclass
class ClaimSummary:
    """Aggregated score for one claim (across all its scenarios)."""
    claim: str
    framework: str
    score_mean: float
    score_std: float
    weight: float
    weighted_score: float


@dataclass
class FrameworkResult:
    """Complete results for one framework."""
    name: str
    overall_score: float
    overall_std: float
    claims: list[ClaimSummary]
    scenarios: list[ScenarioSummary]


@dataclass
class BenchmarkResults:
    """Full benchmark output."""
    version: str = "1.0"
    timestamp: str = ""
    runs_per_scenario: int = 5
    frameworks: list[FrameworkResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


def aggregate_metric(values: list[float]) -> AggregatedMetric:
    """Compute mean, std, min, max for a list of values."""
    if not values:
        return AggregatedMetric(mean=0, std=0, min=0, max=0, values=[])
    mean = statistics.mean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    return AggregatedMetric(
        mean=round(mean, 4),
        std=round(std, 4),
        min=round(min(values), 4),
        max=round(max(values), 4),
        values=[round(v, 4) for v in values],
    )


def aggregate_scenario(results: list[ScenarioResult]) -> ScenarioSummary:
    """Aggregate multiple runs of a single scenario for one framework."""
    if not results:
        raise ValueError("No results to aggregate")

    scenario_id = results[0].scenario_id
    framework = results[0].framework
    scenario = next((s for s in SCENARIOS if s.id == scenario_id), None)

    scores = [r.score for r in results]
    score_agg = aggregate_metric(scores)

    # Aggregate each metric
    metric_keys: set[str] = set()
    for r in results:
        metric_keys.update(r.metrics.keys())

    metrics: dict[str, AggregatedMetric] = {}
    for key in sorted(metric_keys):
        values = []
        for r in results:
            v = r.metrics.get(key)
            if isinstance(v, bool):
                values.append(100.0 if v else 0.0)
            elif isinstance(v, (int, float)):
                values.append(float(v))
        metrics[key] = aggregate_metric(values)

    notes_parts = [r.notes for r in results if r.notes]
    notes = notes_parts[0] if notes_parts else ""

    return ScenarioSummary(
        scenario_id=scenario_id,
        scenario_name=scenario.name if scenario else scenario_id,
        claim=scenario.claim.value if scenario else "",
        framework=framework,
        score_mean=score_agg.mean,
        score_std=score_agg.std,
        metrics=metrics,
        notes=notes,
    )


def compute_claim_score(
    scenario_summaries: list[ScenarioSummary],
    claim: Claim,
) -> ClaimSummary:
    """Compute weighted claim score from scenario summaries."""
    relevant = [s for s in scenario_summaries if s.claim == claim.value]
    if not relevant:
        return ClaimSummary(
            claim=claim.value,
            framework=scenario_summaries[0].framework if scenario_summaries else "",
            score_mean=0,
            score_std=0,
            weight=CLAIM_WEIGHTS[claim],
            weighted_score=0,
        )

    score_mean = statistics.mean([s.score_mean for s in relevant])
    # Propagate uncertainty
    score_std = (
        (sum(s.score_std ** 2 for s in relevant) / len(relevant)) ** 0.5
        if len(relevant) > 1 else relevant[0].score_std
    )
    weight = CLAIM_WEIGHTS[claim]

    return ClaimSummary(
        claim=claim.value,
        framework=relevant[0].framework,
        score_mean=round(score_mean, 2),
        score_std=round(score_std, 2),
        weight=weight,
        weighted_score=round(score_mean * weight, 2),
    )


def compute_framework_result(
    framework: str,
    all_results: list[ScenarioResult],
) -> FrameworkResult:
    """Compute full framework result from raw scenario results."""
    fw_results = [r for r in all_results if r.framework == framework]

    # Group by scenario
    by_scenario: dict[str, list[ScenarioResult]] = {}
    for r in fw_results:
        by_scenario.setdefault(r.scenario_id, []).append(r)

    scenario_summaries = [
        aggregate_scenario(runs)
        for runs in by_scenario.values()
    ]

    # Compute claim scores
    claims = [
        compute_claim_score(scenario_summaries, claim)
        for claim in Claim
    ]

    overall = sum(c.weighted_score for c in claims)
    overall_std = (sum((c.score_std * c.weight) ** 2 for c in claims)) ** 0.5

    return FrameworkResult(
        name=framework,
        overall_score=round(overall, 2),
        overall_std=round(overall_std, 2),
        claims=claims,
        scenarios=scenario_summaries,
    )


def build_results(
    all_results: list[ScenarioResult],
    runs_per_scenario: int = 5,
) -> BenchmarkResults:
    """Build complete benchmark results from all raw results."""
    frameworks = sorted(set(r.framework for r in all_results))

    return BenchmarkResults(
        runs_per_scenario=runs_per_scenario,
        frameworks=[
            compute_framework_result(fw, all_results)
            for fw in frameworks
        ],
        metadata={
            "total_scenarios": len(SCENARIOS),
            "total_runs": len(all_results),
            "frameworks_tested": frameworks,
        },
    )


def results_to_json(results: BenchmarkResults) -> dict[str, Any]:
    """Convert results to JSON-serializable dict."""
    def _agg_to_dict(agg: AggregatedMetric) -> dict[str, Any]:
        return {
            "mean": agg.mean,
            "std": agg.std,
            "min": agg.min,
            "max": agg.max,
            "values": agg.values,
        }

    return {
        "version": results.version,
        "timestamp": results.timestamp,
        "runs_per_scenario": results.runs_per_scenario,
        "metadata": results.metadata,
        "frameworks": [
            {
                "name": fw.name,
                "overall_score": fw.overall_score,
                "overall_std": fw.overall_std,
                "claims": [
                    {
                        "claim": c.claim,
                        "score_mean": c.score_mean,
                        "score_std": c.score_std,
                        "weight": c.weight,
                        "weighted_score": c.weighted_score,
                    }
                    for c in fw.claims
                ],
                "scenarios": [
                    {
                        "scenario_id": s.scenario_id,
                        "scenario_name": s.scenario_name,
                        "claim": s.claim,
                        "score_mean": s.score_mean,
                        "score_std": s.score_std,
                        "notes": s.notes,
                        "metrics": {
                            k: _agg_to_dict(v)
                            for k, v in s.metrics.items()
                        },
                    }
                    for s in fw.scenarios
                ],
            }
            for fw in results.frameworks
        ],
    }


def save_results(results: BenchmarkResults, path: Path) -> None:
    """Save results to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = results_to_json(results)
    path.write_text(json.dumps(data, indent=2))
