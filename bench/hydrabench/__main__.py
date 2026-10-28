"""CLI entry point: python -m bench.hydrabench.runner"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HydraBench: Agent infrastructure resilience benchmarks",
    )
    parser.add_argument(
        "--frameworks",
        nargs="+",
        default=["openhydra", "langgraph", "crewai", "bare"],
        choices=["openhydra", "langgraph", "crewai", "bare"],
        help="Frameworks to benchmark (default: all)",
    )
    parser.add_argument(
        "--runs", type=int, default=5,
        help="Runs per scenario (default: 5)",
    )
    parser.add_argument(
        "--claims",
        nargs="+",
        default=None,
        help="Limit to specific claims (e.g., crash_recovery secret_containment)",
    )
    parser.add_argument(
        "--output", type=str, default="bench/results/latest.json",
        help="Output JSON path (default: bench/results/latest.json)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Build adapters
    adapters = []
    for fw in args.frameworks:
        if fw == "openhydra":
            from .frameworks.openhydra_adapter import OpenHydraAdapter
            adapters.append(OpenHydraAdapter())
        elif fw == "langgraph":
            from .frameworks.langgraph_adapter import LangGraphAdapter
            adapters.append(LangGraphAdapter())
        elif fw == "crewai":
            from .frameworks.crewai_adapter import CrewAIAdapter
            adapters.append(CrewAIAdapter())
        elif fw == "bare":
            from .frameworks.bare_agent_adapter import BareAgentAdapter
            adapters.append(BareAgentAdapter())

    # Parse claims
    from .config import Claim
    claims = None
    if args.claims:
        claims = [Claim(c) for c in args.claims]

    # Run
    from .runner import print_leaderboard, run_benchmark

    output_path = Path(args.output)
    results = asyncio.run(
        run_benchmark(adapters, runs=args.runs, claims=claims, output_path=output_path)
    )

    print_leaderboard(results)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
