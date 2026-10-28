"""JSON reporter for HydraBench results."""

from __future__ import annotations

import json
from pathlib import Path

from ..metrics import BenchmarkResults, results_to_json


def write_json(results: BenchmarkResults, path: Path) -> None:
    """Write results as formatted JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = results_to_json(results)
    path.write_text(json.dumps(data, indent=2))
