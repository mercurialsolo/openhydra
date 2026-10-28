"""Anonymous submission of HydraBench results: strip identity, keep scores, aggregate rows."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.hydrabench.submit import (
    anonymize,
    community_table,
    markdown_table,
    write_submission,
)

RESULTS = (Path(__file__).resolve().parent.parent / "bench" / "results"
           / "real-openhydra-2026-10-28-v1.2.json")


@pytest.fixture
def results() -> dict:
    return json.loads(RESULTS.read_text())


def test_anonymize_replaces_every_framework_name_with_the_codename(results):
    out = anonymize(results, codename="quiet-otter")
    assert [f["name"] for f in out["frameworks"]] == ["quiet-otter"]
    assert out["metadata"]["frameworks_tested"] == ["quiet-otter"]
    assert "OpenHydra" not in json.dumps(out)


def test_anonymize_drops_free_text_and_keeps_scores(results):
    out = anonymize(results, codename="quiet-otter")
    fw = out["frameworks"][0]
    assert all("notes" not in s for s in fw["scenarios"])
    assert fw["claims"] == results["frameworks"][0]["claims"]
    before = [s["score_mean"] for s in results["frameworks"][0]["scenarios"]]
    assert [s["score_mean"] for s in fw["scenarios"]] == before


def test_anonymize_keeps_only_the_date_of_the_timestamp(results):
    out = anonymize(results, codename="quiet-otter")
    assert out["timestamp"] == "2026-10-28"
    assert out["submitted"] is True


def test_codename_is_two_words_when_not_given(results):
    out = anonymize(results)
    name = out["frameworks"][0]["name"]
    assert len(name.split("-")) == 2


def test_write_submission_names_the_file_by_codename_and_date(results, tmp_path):
    path = write_submission(results, tmp_path, codename="quiet-otter")
    assert path.name == "quiet-otter-2026-10-28.json"
    assert json.loads(path.read_text())["frameworks"][0]["name"] == "quiet-otter"


def test_community_table_has_one_row_per_submission_and_a_column_per_claim(results, tmp_path):
    write_submission(results, tmp_path, codename="quiet-otter")
    write_submission(results, tmp_path, codename="loud-heron")
    rows = community_table(tmp_path)
    assert [r["codename"] for r in rows] == ["loud-heron", "quiet-otter"]
    assert rows[0]["crash_recovery"] == 95.0
    assert rows[0]["cost_control"] == 40.0


def test_a_multi_framework_file_is_refused_unless_one_is_selected(results):
    first = results["frameworks"][0]
    two = {**results, "frameworks": [first, {**first, "name": "B"}]}
    with pytest.raises(ValueError, match="--framework"):
        anonymize(two, codename="quiet-otter")
    out = anonymize(two, codename="quiet-otter", framework="B")
    assert [f["name"] for f in out["frameworks"]] == ["quiet-otter"]


def test_markdown_table_has_a_header_and_one_line_per_row(results, tmp_path):
    write_submission(results, tmp_path, codename="quiet-otter")
    md = markdown_table(community_table(tmp_path))
    assert md.splitlines()[0].startswith("| codename |")
    assert "| quiet-otter |" in md
