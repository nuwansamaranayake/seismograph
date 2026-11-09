"""Build the standalone field guide: docs/guide/seismograph-guide.html.

    python scripts/build_guide.py

The guide states the instrument's published limits. Those are not typed into the page:
this script reads the limits sentence from EVAL.md and the operating curve from
eval_report.md and injects them into docs/guide/guide.template.html. It also copies the
guide's screenshots from web/public/guide, where scripts/seed_demo.py's walkthrough was
captured, so the in-app guide and the standalone one show the same images.

A missing source, table or placeholder fails the build. A guide that states a limit it
could not read is worse than no guide.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GUIDE = REPO / "docs" / "guide"
SHOTS = REPO / "web" / "public" / "guide"
MISS_BELOW = 0.80       # EVAL.md's detection floor: lower CI bound under this is a miss


def limits_sentence(eval_md: str) -> str:
    match = re.search(r"<!-- LIMITS -->\s*(.+?)\s*<!-- /LIMITS -->", eval_md, re.S)
    if not match:
        raise ValueError("EVAL.md has no <!-- LIMITS --> block")
    return " ".join(match.group(1).split())


def table_after(markdown: str, heading: str) -> list[dict[str, str]]:
    start = markdown.find(heading)
    if start < 0:
        raise ValueError(f'eval_report.md has no section "{heading}"')
    rows: list[list[str]] = []
    for line in markdown[start + len(heading):].splitlines():
        line = line.strip()
        if line.startswith("|"):
            rows.append([cell.strip() for cell in line.strip("|").split("|")])
        elif rows:
            break
    if len(rows) < 3:
        raise ValueError(f'section "{heading}" has no table')
    header, _, *body = rows
    return [dict(zip(header, cells, strict=True)) for cells in body]


def false_alarm(markdown: str) -> str:
    match = re.search(r"false alarm rate: \*\*([\d.]+)\*\* \(95% CI ([\d.]+)-([\d.]+)\)", markdown)
    if not match:
        raise ValueError("eval_report.md has no false alarm rate line")
    rate, low, high = match.groups()
    return f"{rate} (95% CI {low} to {high})"


def shift_rows(rows: list[dict[str, str]]) -> str:
    out = []
    for row in rows:
        low = float(row["95% CI"].split("-")[0])
        css = ' class="miss"' if low < MISS_BELOW else ""
        out.append(
            f'          <tr{css}><td>{row["shift"]}</td><td class="num">{row["detected"]}</td>'
            f'<td class="num">{row["sensitivity"]}</td><td class="num">{row["95% CI"]}</td>'
            f'<td class="num">{row["median latency"]} points</td></tr>')
    return "\n".join(out)


def render(template: str, eval_md: str, report: str) -> str:
    values = {
        "{{LIMITS}}": limits_sentence(eval_md),
        "{{SHIFT_ROWS}}": shift_rows(table_after(report, "## Detection vs defect magnitude")),
        "{{FALSE_ALARM}}": false_alarm(report),
    }
    for placeholder, value in values.items():
        if placeholder not in template:
            raise ValueError(f"template has no {placeholder}")
        template = template.replace(placeholder, value)
    left = re.findall(r"\{\{[A-Z_]+\}\}", template)
    if left:
        raise ValueError(f"unfilled placeholders: {left}")
    return template


def main() -> None:
    html = render(
        (GUIDE / "guide.template.html").read_text(encoding="utf-8"),
        (REPO / "EVAL.md").read_text(encoding="utf-8"),
        (REPO / "eval_report.md").read_text(encoding="utf-8"),
    )
    (GUIDE / "seismograph-guide.html").write_text(html, encoding="utf-8", newline="\n")
    images = GUIDE / "img"
    images.mkdir(exist_ok=True)
    needed = sorted(set(re.findall(r'src="img/([^"]+)"', html)))
    for name in needed:
        source = SHOTS / name
        if not source.is_file():
            raise SystemExit(f"missing screenshot {source}; capture the walkthrough first")
        shutil.copyfile(source, images / name)
    print(f"guide written: {GUIDE / 'seismograph-guide.html'} ({len(html)} bytes, {len(needed)} images)")


if __name__ == "__main__":
    main()
