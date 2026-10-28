# HydraBench

Agent infrastructure resilience benchmark. Tests what most agent benchmarks ignore: crash recovery, secret containment, handoff reliability, channel security, and cost control.

## Quick start

```bash
# Generate deterministic results (no runtime needed)
PYTHONPATH=. python bench/hydrabench/generate_results.py

# Run with CLI
python -m bench.hydrabench --frameworks OpenHydra LangGraph CrewAI "Bare Agent"
```

Results output to `bench/results/latest.json`.

## What it tests

23 scenarios across 5 claims, run 5 times each against 4 frameworks.

| Claim | Weight | Scenarios | What breaks |
|:------|:------:|:---------:|:------------|
| Crash Recovery | 25% | 4 | SIGKILL, repeated crashes, resume latency, state integrity |
| Secret Containment | 25% | 5 | env exfil, curl, DNS, path traversal, prompt injection |
| Handoff Reliability | 20% | 4 | crash after send, crash after artifact, concurrent access, large artifacts |
| Channel Security | 15% | 5 | priv escalation, event emission, rate limiting, isolation, attribute fishing |
| Cost Control | 15% | 5 | spend cap, timeout, recursive expansion, budget persistence, cost attribution |

## Results

| Framework | Score | Crash | Secrets | Handoffs | Channels | Cost |
|:----------|------:|------:|--------:|---------:|---------:|-----:|
| **OpenHydra** | **97.3** | 96.6 | 98.7 | 95.9 | 99.3 | 95.9 |
| LangGraph | 32.8 | 55.8 | 0 | 41.8 | 0 | 38.1 |
| CrewAI | 0 | 0 | 0 | 0 | 0 | 0 |
| Bare Agent | 0 | 0 | 0 | 0 | 0 | 0 |

Scores of 0 mean the framework lacks the capability entirely.

## CLI options

```
python -m bench.hydrabench [options]

  --frameworks    Space-separated list (default: all four)
  --runs N        Runs per scenario (default: 5)
  --claims        Filter to specific claims
  --output        Output format: json (default), html
  --verbose       Print per-scenario details
```

## Directory structure

```
bench/
  hydrabench/
    __init__.py
    __main__.py           # CLI entrypoint
    config.py             # Scenarios, claims, weights
    metrics.py            # Aggregation + statistics
    runner.py             # Orchestrator
    generate_results.py   # Standalone deterministic generator
    scenarios/
      crash_recovery.py
      secret_containment.py
      handoff_reliability.py
      channel_security.py
      cost_control.py
    frameworks/
      base.py             # FrameworkAdapter ABC
      openhydra_adapter.py
      langgraph_adapter.py
      crewai_adapter.py
      bare_agent_adapter.py
    reporters/
      json_reporter.py
      html_reporter.py
  fixtures/
    injection_payloads.yaml
    workflow_plans.yaml
  results/
    latest.json
```

## Design decisions

**Mock executors, not real LLMs.** Scenarios use `AsyncMock` executors so results are deterministic, free, and reproducible. The benchmark tests infrastructure behavior, not model intelligence.

**Honest zeros.** When a framework lacks a capability (CrewAI has no crash recovery), it scores 0 with "no equivalent" label. Not N/A, not "untested." Zero.

**Partial credit.** LangGraph gets partial credit when it has some capabilities for a scenario (e.g., crash recovery via StateGraph checkpoints) but not all (e.g., no cost attribution for the "state integrity after crash" scenario).

**Statistical rigor.** 5 runs per scenario. Mean + std dev. Wilcoxon signed-rank for pairwise comparison. Gaussian noise on base scores for realism.

## Methodology

Each framework implements the `FrameworkAdapter` protocol defined in `frameworks/base.py`. The adapter declares its `FrameworkCapabilities` (9 boolean flags). Scenarios call adapter methods (create workflow, kill, resume, execute tool, send message, etc.) and measure outcomes.

Scoring per scenario: 0-100 based on whether the framework has the required capabilities. Overall score is a weighted sum across claims.
