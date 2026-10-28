"""HTML reporter: generates a standalone results page."""

from __future__ import annotations

from pathlib import Path

from ..metrics import BenchmarkResults, results_to_json


def write_html(results: BenchmarkResults, path: Path) -> None:
    """Write a standalone HTML results page."""
    import json

    data = results_to_json(results)
    data_json = json.dumps(data, indent=2)

    ranked = sorted(results.frameworks, key=lambda f: f.overall_score, reverse=True)

    rows = ""
    for i, fw in enumerate(ranked, 1):
        medal = ["🥇", "🥈", "🥉", ""][min(i - 1, 3)]
        claims_html = ""
        for c in fw.claims:
            claims_html += f'<td>{c.score_mean:.0f}<small>+-{c.score_std:.0f}</small></td>'
        rows += f"""
        <tr>
            <td>{medal} {i}</td>
            <td><strong>{fw.name}</strong></td>
            <td><strong>{fw.overall_score:.1f}</strong></td>
            {claims_html}
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HydraBench Results</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 900px; margin: 0 auto; padding: 24px; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 8px 12px; border-bottom: 1px solid #eee; text-align: left; }}
th {{ background: #f7f6f3; font-weight: 600; }}
small {{ color: #888; }}
pre {{ background: #f7f6f3; padding: 16px; border-radius: 6px; overflow-x: auto; font-size: 0.85rem; }}
</style>
</head>
<body>
<h1>HydraBench Results</h1>
<p>Agent infrastructure resilience benchmark. {results.runs_per_scenario} runs per scenario, {len(results.frameworks)} frameworks tested.</p>
<table>
<thead>
<tr>
<th>Rank</th><th>Framework</th><th>Score</th>
<th>Crash</th><th>Secrets</th><th>Handoffs</th><th>Channels</th><th>Cost</th>
</tr>
</thead>
<tbody>{rows}
</tbody>
</table>
<h2>Raw Data</h2>
<pre>{data_json}</pre>
</body>
</html>"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)
