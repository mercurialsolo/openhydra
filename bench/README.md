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

Three measured passes on OpenHydra, 23 scenarios × 5 runs each (345 runs), real primitives and a mock
LLM. Rows, not an overall: with a mock executor the primitives are deterministic (std dev 0 on
every row), and the weighted total hides what each pass found.

| Claim | v1, 2026-10-27 | v1.1, 2026-10-28 real kill | v1.2, 2026-10-28 recover_workflow |
|---|---:|---:|---:|
| Crash recovery | 100 (vacuous: the kill was a pause) | **32.5** | **95** |
| Secret containment | 100 | 100 | 100 |
| Handoff reliability | 100 (half vacuous) | 100 | 100 |
| Channel security | 90 (adapter bug) | 100 | 100 |
| Cost control | 40 | 40 | 40 |

- `results/real-openhydra-2026-10-27.json`, `results/real-openhydra-2026-10-28-v1.1.json`,
  `results/real-openhydra-2026-10-28-v1.2.json`. `results/latest.json` is a copy of v1.2.
- Cost control is 40 in every pass because the engine has no workflow-level `budget_usd`,
  `max_steps` or `max_duration_minutes`; cc-1 spends $2.00 against a $1.00 cap. Those are engine gaps,
  not harness bugs.
- The leaderboard published in February (OpenHydra 97.3, LangGraph 32.8, CrewAI 0, Bare 0) came from
  `hydrabench/generate_results.py`, a capability matrix plus Gaussian noise. It is kept as
  `results/latest.generated-2026-02-23.json` and must not be presented as a run.
- LangGraph, CrewAI and the bare agent have not been run. Their adapters are scripted simulations;
  treat the capability matrix as an audit against their docs, not a measurement.

Full account of each pass and every scenario: the talk record in the coach repo,
`talks/2026-10-28-beyond-agent-accuracy/RESULTS.md`.

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

**Statistical rigor.** 5 runs per scenario. Mean + std dev. Wilcoxon signed-rank for pairwise comparison. (The generator script's Gaussian noise was decoration; measured passes have std dev 0.)

## Methodology

Each framework implements the `FrameworkAdapter` protocol defined in `frameworks/base.py`. The adapter declares its `FrameworkCapabilities` (9 boolean flags). Scenarios call adapter methods (create workflow, kill, resume, execute tool, send message, etc.) and measure outcomes.

Scoring per scenario: 0-100 based on whether the framework has the required capabilities. Overall score is a weighted sum across claims.
