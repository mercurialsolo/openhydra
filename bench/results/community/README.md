# Community results

One file per submitted HydraBench run, written by `python -m bench.hydrabench.submit`.

What a file holds: the score per claim and per scenario, the per-metric mean, std, min, max and
values across runs, the run count, the elapsed time, and the date. What it does not hold: the
framework's name (replaced by a two-word codename), the free-text `notes` field, the time of day,
or anything about the machine, the person or the customer. The LLM is a mock, so no prompt or
output is ever in a results file to begin with.

## Submit a run

```bash
cp bench/hydrabench/frameworks/template_adapter.py mypkg/adapter.py   # then rename the class to MyAdapter
PYTHONPATH=. python -m bench.hydrabench.check mypkg.adapter:MyAdapter          # fix errors and vacuous kills first
PYTHONPATH=. python -m bench.hydrabench --frameworks mypkg.adapter:MyAdapter --runs 5 --output mine.json
python -m bench.hydrabench.submit mine.json            # writes bench/results/community/<codename>-<date>.json
git add bench/results/community/ && git commit -m "HydraBench: community submission"
```

CI runs `tests/test_community_submissions.py` on the pull request: one framework per file, a
codename for its name, no notes, a date-only timestamp, the five claims. `openhydra-reference-*.json`
is the maintainers' own v1.2 run, labelled rather than anonymous, so the table has a row on day one.

Open a pull request from any GitHub account. The file is the whole submission; the account is the
only identity involved, so use a throwaway if that matters to you. Keep the codename the tool gave
you, or pass `--codename` if you want to recognise your own row later.

## Read the table

```bash
python -m bench.hydrabench.submit --table            # add --markdown to paste into an issue
```

One row per submission, one column per claim. Read rows, not the overall: the weights are
opinions, and cost control is where every runtime we have seen scores the same.
