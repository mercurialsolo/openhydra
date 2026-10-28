"""python -m bench.hydrabench.check: declared vs observed, vacuous kills, and errors."""
from __future__ import annotations

from bench.hydrabench.check import assess, main
from bench.hydrabench.config import ScenarioResult
from bench.hydrabench.frameworks.base import FrameworkCapabilities


def _r(sid, score, metrics=None, notes=""):
    return ScenarioResult(scenario_id=sid, framework="x", run=0, metrics=metrics or {},
                          score=score, notes=notes)


def test_assess_flags_a_kill_that_landed_after_the_workflow_finished():
    caps = FrameworkCapabilities(crash_recovery=True)
    report = assess([_r("cr-1", 100, {"running_at_kill": False, "completed_at_kill": 5})], caps)
    assert report.vacuous == ["cr-1"]
    assert report.errors == []


def test_assess_does_not_flag_a_real_kill():
    caps = FrameworkCapabilities(crash_recovery=True)
    report = assess([_r("cr-1", 32.5, {"running_at_kill": True, "completed_at_kill": 1})], caps)
    assert report.vacuous == []


def test_assess_collects_scenarios_that_raised():
    report = assess([_r("cc-1", 0, notes="Error: boom")], FrameworkCapabilities())
    assert report.errors == ["cc-1"]


def test_assess_reports_declared_and_observed_per_claim():
    caps = FrameworkCapabilities(secret_stripping=True)
    report = assess([_r("sc-1", 100), _r("cr-1", 0, notes="0 (no equivalent)")], caps)
    rows = {row.claim: row for row in report.rows}
    assert rows["secret_containment"].declared == ["secret_stripping"]
    assert rows["secret_containment"].score == 100
    assert rows["crash_recovery"].declared == []
    assert rows["crash_recovery"].score == 0


def test_check_cli_passes_the_template_adapter(capsys):
    code = main(["bench.hydrabench.frameworks.template_adapter:TemplateAdapter"])
    out = capsys.readouterr().out
    assert code == 0
    assert "crash_recovery" in out and "no errors" in out
