"""Every file under bench/results/community/ is a valid anonymized submission."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from bench.hydrabench.submit import CODENAME_RE, validate_submission

COMMUNITY = Path(__file__).resolve().parent.parent / "bench" / "results" / "community"
FILES = sorted(COMMUNITY.glob("*.json"))


def test_there_is_at_least_the_reference_row():
    assert FILES, "bench/results/community/ has no submissions"


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_submission_is_anonymized_and_complete(path):
    data = json.loads(path.read_text())
    assert validate_submission(data) == []
    name = data["frameworks"][0]["name"]
    assert re.fullmatch(CODENAME_RE, name)
    assert path.name == f"{name}-{data['timestamp']}.json"


def test_validate_names_each_problem():
    bad = {"version": "1.0", "timestamp": "2026-10-28T10:00:00", "submitted": False,
           "frameworks": [{"name": "OpenHydra", "claims": [], "scenarios": [{"notes": "x"}]},
                          {"name": "other", "claims": [], "scenarios": []}]}
    problems = validate_submission(bad)
    assert any("one framework" in p for p in problems)
    assert any("codename" in p for p in problems)
    assert any("notes" in p for p in problems)
    assert any("date" in p for p in problems)
    assert any("submitted" in p for p in problems)
    assert any("five claims" in p for p in problems)
