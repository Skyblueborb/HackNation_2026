"""Human-readable error report: the most common (field, verdict) mistakes a
run makes, with one concrete example each.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any


def write_errors_md(mismatches: list[dict[str, Any]], out_path: Path, top_n: int = 30) -> None:
    """mismatches: list of {'file', 'field', 'expected', 'got', 'verdict'}
    entries for every FP/FN/FPFN leaf (TP/TN excluded by construction).
    Writes a markdown table of the top_n most frequent (field, verdict)
    combinations with their counts, followed by one example per
    combination."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    combo_counts: Counter[tuple[str, str]] = Counter()
    first_example: dict[tuple[str, str], dict[str, Any]] = {}
    for m in mismatches:
        key = (m["field"], m["verdict"])
        combo_counts[key] += 1
        if key not in first_example:
            first_example[key] = m

    top = combo_counts.most_common(top_n)

    lines: list[str] = []
    lines.append("# Evaluation errors")
    lines.append("")
    lines.append(f"Total mismatches recorded: {sum(combo_counts.values())}")
    lines.append("")

    if not top:
        lines.append("No mismatches recorded.")
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    lines.append(f"## Top {len(top)} (field, verdict) combinations")
    lines.append("")
    lines.append("| field | verdict | count |")
    lines.append("|---|---|---|")
    for (fkey, verdict), count in top:
        lines.append(f"| `{fkey}` | {verdict} | {count} |")
    lines.append("")

    lines.append("## Examples")
    lines.append("")
    for (fkey, verdict), count in top:
        example = first_example[(fkey, verdict)]
        lines.append(f"### `{fkey}` — {verdict} ({count} occurrences)")
        lines.append("")
        lines.append(f"- file: `{example['file']}`")
        lines.append(f"- expected: `{example['expected']!r}`")
        lines.append(f"- got: `{example['got']!r}`")
        lines.append("")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
