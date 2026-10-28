"""Share a HydraBench run without saying who you are.

    python -m bench.hydrabench.submit mine.json [--codename quiet-otter] [--out bench/results/community]
    python -m bench.hydrabench.submit --table [--dir bench/results/community]

``anonymize`` keeps scores, per-metric statistics and timings. It replaces the framework name with a
codename, drops the free-text ``notes`` (the one field that can carry a path or an error message),
and keeps only the date of the timestamp. Nothing else in a results file identifies a machine, a
person or a customer: the LLM is a mock, so no prompt or output is ever recorded.

To submit: commit the written file under ``bench/results/community/`` and open a pull request from
any GitHub account. The file is the whole submission; the account is the only identity involved.
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from pathlib import Path

ADJECTIVES = ["quiet", "loud", "brisk", "calm", "dry", "early", "faint", "grey", "keen", "late",
              "mild", "odd", "pale", "quick", "rare", "slow", "tall", "vast", "warm", "young"]
ANIMALS = ["otter", "heron", "lynx", "finch", "badger", "ibis", "newt", "crane", "mole", "wren",
           "stoat", "tern", "vole", "shrew", "egret", "pike", "hare", "moth", "kite", "seal"]

COMMUNITY_DIR = Path("bench/results/community")
FREE_TEXT_FIELDS = ("notes",)


def make_codename(rng: random.Random | None = None) -> str:
    rng = rng or random.SystemRandom()
    return f"{rng.choice(ADJECTIVES)}-{rng.choice(ANIMALS)}"


def anonymize(results: dict, codename: str | None = None) -> dict:
    """Return a copy of ``results`` with identity removed and scores intact."""
    out = copy.deepcopy(results)
    codename = codename or make_codename()
    for fw in out.get("frameworks", []):
        fw["name"] = codename
        for scenario in fw.get("scenarios", []):
            for field in FREE_TEXT_FIELDS:
                scenario.pop(field, None)
    meta = out.setdefault("metadata", {})
    if "frameworks_tested" in meta:
        meta["frameworks_tested"] = [codename for _ in meta["frameworks_tested"]]
    ts = str(out.get("timestamp", ""))
    out["timestamp"] = ts[:10]
    out["submitted"] = True
    return out


def write_submission(results: dict, out_dir: Path, codename: str | None = None) -> Path:
    out = anonymize(results, codename)
    name = out["frameworks"][0]["name"] if out.get("frameworks") else (codename or make_codename())
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


def print_table(rows: list[dict]) -> None:
    claims = ["crash_recovery", "secret_containment", "handoff_reliability", "channel_security", "cost_control"]
    head = f"{'codename':14} {'date':10} " + " ".join(f"{c[:12]:>12}" for c in claims)
    print(head)
    for r in rows:
        print(f"{r['codename']:14} {r['date']:10} " + " ".join(f"{r.get(c, float('nan')):12.1f}" for c in claims))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Anonymize a HydraBench results file for submission.")
    parser.add_argument("results", nargs="?", help="results JSON written by python -m bench.hydrabench --output")
    parser.add_argument("--codename", help="two words, e.g. quiet-otter (default: random)")
    parser.add_argument("--out", default=str(COMMUNITY_DIR), help="directory for the anonymized file")
    parser.add_argument("--table", action="store_true", help="print the community table instead")
    parser.add_argument("--dir", default=str(COMMUNITY_DIR), help="community directory for --table")
    args = parser.parse_args(argv)
    if args.table:
        print_table(community_table(Path(args.dir)))
        return 0
    if not args.results:
        parser.error("results file required unless --table")
    results = json.loads(Path(args.results).read_text())
    path = write_submission(results, Path(args.out), args.codename)
    print(f"wrote {path}")
    print("submit it: git add", path, "&& git commit -m 'HydraBench: community submission' && open a PR from any GitHub account")
    print("the file holds scores, per-metric statistics and timings only; the codename is the only name in it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
