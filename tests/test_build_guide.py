"""The standalone guide states the published limits, so it is built from the eval files
and checked against them: the sentence is verbatim, misses are marked, nothing is typed."""
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("build_guide", ROOT / "scripts" / "build_guide.py")
build_guide = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_guide)

EVAL_MD = (ROOT / "EVAL.md").read_text(encoding="utf-8")
REPORT = (ROOT / "eval_report.md").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "docs" / "guide" / "guide.template.html").read_text(encoding="utf-8")


def test_the_guide_carries_the_limits_sentence_verbatim_and_leaves_no_placeholder():
    html = build_guide.render(TEMPLATE, EVAL_MD, REPORT)
    assert build_guide.limits_sentence(EVAL_MD) in html
    assert "{{" not in html
    assert build_guide.false_alarm(REPORT) in html


def test_every_row_of_the_operating_curve_is_shown_and_the_misses_are_marked():
    rows = build_guide.table_after(REPORT, "## Detection vs defect magnitude")
    html = build_guide.shift_rows(rows)
    assert html.count("<tr") == len(rows) >= 5
    marked = re.findall(r'<tr class="miss"><td>([^<]+)</td>', html)
    expected = [r["shift"] for r in rows if float(r["95% CI"].split("-")[0]) < build_guide.MISS_BELOW]
    assert marked == expected and marked, "the documented misses must be visibly marked"
    assert all(r["detected"] in html for r in rows)


def test_the_committed_guide_is_current_with_the_eval_files_and_its_images_exist():
    guide = ROOT / "docs" / "guide" / "seismograph-guide.html"
    html = guide.read_text(encoding="utf-8")
    assert html == build_guide.render(TEMPLATE, EVAL_MD, REPORT), "run python scripts/build_guide.py"
    images = re.findall(r'src="img/([^"]+)"', html)
    assert len(images) == 6
    for name in images:
        assert (guide.parent / "img" / name).is_file(), name
        assert (ROOT / "web" / "public" / "guide" / name).is_file(), name


def test_the_guide_copy_follows_the_writing_rules():
    text = re.sub(r"<style>.*?</style>|<pre>.*?</pre>|<[^>]+>", " ", TEMPLATE, flags=re.S)
    assert "—" not in text, "no em dashes"
    for word in ("AI-powered", "intelligent", "smart", "revolutioni", "cutting-edge", "unlock"):
        assert word.lower() not in text.lower(), word


@pytest.mark.parametrize("call,message", [
    (lambda: build_guide.limits_sentence("no markers here"), "no <!-- LIMITS --> block"),
    (lambda: build_guide.table_after("# nothing", "## Detection"), 'no section "## Detection"'),
    (lambda: build_guide.table_after("## Detection\n\nprose only\n", "## Detection"), "has no table"),
    (lambda: build_guide.false_alarm("no rate"), "no false alarm rate line"),
    (lambda: build_guide.render("no placeholders", EVAL_MD, REPORT), "template has no"),
    (lambda: build_guide.render(TEMPLATE + "{{EXTRA_ONE}}", EVAL_MD, REPORT), "unfilled placeholders"),
])
def test_a_source_it_cannot_read_fails_the_build(call, message):
    with pytest.raises(ValueError, match=message):
        call()
