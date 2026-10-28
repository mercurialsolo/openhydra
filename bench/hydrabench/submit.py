"""Share a HydraBench run without saying who you are.

    python -m bench.hydrabench.submit mine.json [--codename quiet-otter] [--framework NAME]
    python -m bench.hydrabench.submit --table [--markdown]

``anonymize`` keeps scores, per-metric statistics and timings. It replaces the framework name with
a codename, drops the free-text ``notes`` (the one field that can carry a path or an error
message), and keeps only the date of the timestamp. Nothing else in a results file identifies a
machine, a person or a customer: the LLM is a mock, so no prompt or output is ever recorded.

To submit: commit the written file under ``bench/results/community/`` and open a pull request from
any GitHub account. The file is the whole submission; the account is the only identity involved.
Run ``python -m bench.hydrabench.check`` first: an error is scored 0 and its message is dropped
here, so a broken adapter would submit as a clean-looking row of zeros.
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import re
import sys
from pathlib import Path

ADJECTIVES = ["quiet", "loud", "brisk", "calm", "dry", "early", "faint", "grey", "keen", "late",
              "mild", "odd", "pale", "quick", "rare", "slow", "tall", "vast", "warm", "young"]
ANIMALS = ["otter", "heron", "lynx", "finch", "badger", "ibis", "newt", "crane", "mole", "wren",
           "stoat", "tern", "vole", "shrew", "egret", "pike", "hare", "moth", "kite", "seal"]

COMMUNITY_DIR = Path("bench/results/community")
FREE_TEXT_FIELDS = ("notes",)
CODENAME_RE = r"[a-z0-9]+-[a-z0-9]+"
CLAIMS = ["crash_recovery", "secret_containment", "handoff_reliability", "channel_security",
          "cost_control"]


def make_codename(rng: random.Random | None = None) -> str:
    rng = rng or random.SystemRandom()
    return f"{rng.choice(ADJECTIVES)}-{rng.choice(ANIMALS)}"


def anonymize(results: dict, codename: str | None = None, framework: str | None = None) -> dict:
    """Return a copy of ``results`` holding one framework, renamed, with identity removed."""
    out = copy.deepcopy(results)
    frameworks = out.get("frameworks", [])
    if framework is not None:
        frameworks = [f for f in frameworks if f.get("name") == framework]
        if not frameworks:
            raise ValueError(f"no framework named {framework!r} in the results file")
    if len(frameworks) != 1:
        names = [f.get("name") for f in frameworks]
        raise ValueError(
            f"a submission holds one framework; this file has {names}. Pick one with --framework"
        )
    codename = codename or make_codename()
    if not re.fullmatch(CODENAME_RE, codename):
        raise ValueError(f"codename must look like quiet-otter, got {codename!r}")
    fw = frameworks[0]
    fw["name"] = codename
    for scenario in fw.get("scenarios", []):
        for field in FREE_TEXT_FIELDS:
            scenario.pop(field, None)
    out["frameworks"] = [fw]
    meta = out.setdefault("metadata", {})
    if "frameworks_tested" in meta:
        meta["frameworks_tested"] = [codename]
    out["timestamp"] = str(out.get("timestamp", ""))[:10]
    out["submitted"] = True
    return out


def validate_submission(data: dict) -> list[str]:
    """Problems with an anonymized file; empty when it is fit to merge."""
    problems: list[str] = []
    frameworks = data.get("frameworks", [])
    if len(frameworks) != 1:
        problems.append(f"a submission holds exactly one framework, found {len(frameworks)}")
    for fw in frameworks:
        if not re.fullmatch(CODENAME_RE, str(fw.get("name", ""))):
            problems.append(f"framework name {fw.get('name')!r} is not a codename")
        if any("notes" in s for s in fw.get("scenarios", [])):
            problems.append("scenario notes must be dropped")
        if [c.get("claim") for c in fw.get("claims", [])] != CLAIMS:
            problems.append("five claims expected in the standard order")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(data.get("timestamp", ""))):
        problems.append("timestamp must be a date only")
    if data.get("submitted") is not True:
        problems.append("submitted must be true (write the file with submit.py)")
    return problems


def write_submission(
    results: dict, out_dir: Path, codename: str | None = None, framework: str | None = None,
) -> Path:
    out = anonymize(results, codename, framework)
    name = out["frameworks"][0]["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}-{out['timestamp']}.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    return path


def community_table(community_dir: Path) -> list[dict]:
    """One row per submitted file: codename, date, and the mean score per claim."""
    rows = []
    for path in sorted(community_dir.glob("*.json")):
        data = json.loads(path.read_text())
        for fw in data.get("frameworks", []):
            row = {"codename": fw["name"], "date": data.get("timestamp", "")}
            for claim in fw.get("claims", []):
                row[claim["claim"]] = claim["score_mean"]
            row["overall"] = fw.get("overall_score")
            rows.append(row)
    return rows


def text_table(rows: list[dict]) -> str:
    head = f"{'codename':20} {'date':10} " + " ".join(f"{c[:12]:>12}" for c in CLAIMS)
    lines = [head]
    for r in rows:
        cells = " ".join(f"{r.get(c, float('nan')):12.1f}" for c in CLAIMS)
        lines.append(f"{r['codename']:20} {r['date']:10} {cells}")
    return "\n".join(lines)


def markdown_table(rows: list[dict]) -> str:
    lines = ["| codename | date | " + " | ".join(CLAIMS) + " |",
             "|---|---|" + "---:|" * len(CLAIMS)]
    for r in rows:
        cells = " | ".join(f"{r.get(c, float('nan')):.1f}" for c in CLAIMS)
        lines.append(f"| {r['codename']} | {r['date']} | {cells} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Anonymize a HydraBench results file.")
    parser.add_argument("results", nargs="?", help="JSON from python -m bench.hydrabench --output")
    parser.add_argument("--codename", help="two words, e.g. quiet-otter (default: random)")
    parser.add_argument("--framework", help="which framework to submit from a multi-framework file")
    parser.add_argument("--out", default=str(COMMUNITY_DIR), help="directory for the file")
    parser.add_argument("--table", action="store_true", help="print the community table")
    parser.add_argument("--markdown", action="store_true", help="with --table: markdown output")
    parser.add_argument("--dir", default=str(COMMUNITY_DIR), help="community directory")
    args = parser.parse_args(argv)
    if args.table:
        rows = community_table(Path(args.dir))
        print(markdown_table(rows) if args.markdown else text_table(rows))
        return 0
    if not args.results:
        parser.error("results file required unless --table")
    results = json.loads(Path(args.results).read_text())
    path = write_submission(results, Path(args.out), args.codename, args.framework)
    print(f"wrote {path}")
    print("the file holds scores, per-metric statistics and timings; the codename is its only name")
    print(f"submit it: git add {path} && git commit -m 'HydraBench: community submission'"
          " && open a pull request from any GitHub account")
    return 0


if __name__ == "__main__":
    sys.exit(main())
