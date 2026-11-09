"""`seismo gate`: exit codes are the interface a CI job reads, so they are what is tested."""
import json
import sys

import pytest

from app import gate_cli
from app.gate_cli import GateConfigError, gate, latest_alarm, resolve_sut

FULL = """
contract: refund-gate
subject: support-agent
invariants:
  - field: eligibility_decision
    under: [repeat_run, irrelevant_context, reordering, format, paraphrase]
    relation: equal
  - field: cited_policy_ids
    under: [repeat_run]
    relation: jaccard_at_least
    threshold: 0.85
allowed_variation:
  - field: response_wording
    rule: semantically_equivalent
run_policy: {samples: 20, configs: 1, confidence: 0.95}
gate: {max_decision_flip_rate: 0.15, max_malformed_rate: 0.05}
probes:
  - id: refund-basic
    input: "Customer bought a blender 12 days ago, unopened. Are they refund eligible?"
"""


@pytest.fixture()
def contract(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    path = tmp_path / "contract.yaml"
    path.write_text(FULL, encoding="utf-8")
    return str(path)


def test_a_healthy_system_exits_0_and_says_why(contract, capsys):
    assert gate(contract, "policy", points=3, seed=7) == 0
    out = capsys.readouterr().out
    assert "## Seismograph gate: PASS" in out
    assert "every declared tolerance held" in out
    assert "`policy` is a built-in simulator, not your system." in out
    assert "refund-basic / paraphrase: no accepted paraphrase variants generated yet" in out
    assert "Control chart warms up after 8 points. Have 3." in out


def test_a_planted_defect_exits_1_and_names_the_cell(contract, capsys):
    assert gate(contract, "format-sensitive", points=2, seed=7) == 1
    out = capsys.readouterr().out
    assert "## Seismograph gate: BLOCK" in out and "- flip rate" in out
    row = next(line for line in out.splitlines() if line.startswith("| refund-basic | format |"))
    assert float(row.split("|")[4]) > 0.15


def test_the_summary_is_appended_to_the_github_step_summary(contract, tmp_path, monkeypatch):
    target = tmp_path / "summary.md"
    target.write_text("earlier step\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    assert gate(contract, "stable", points=2, seed=7) == 0
    text = target.read_text(encoding="utf-8")
    assert text.startswith("earlier step\n") and "## Seismograph gate: PASS" in text
    explicit = tmp_path / "explicit.md"
    assert gate(contract, "stable", points=1, seed=7, summary_path=str(explicit)) == 0
    assert "## Seismograph gate: PASS" in explicit.read_text(encoding="utf-8")


def test_the_chart_table_appears_once_warm_and_the_jump_signals(contract, capsys):
    assert gate(contract, "jump", points=14, seed=11) == 1
    out = capsys.readouterr().out
    assert "| t | worst flip rate | upper limit | signal |" in out
    signals = [line.split("|")[4].strip() for line in out.splitlines() if line.startswith("| 1")]
    assert "we1" in signals


def test_fail_on_alarm_blocks_a_run_the_tolerance_alone_would_pass(contract, tmp_path, capsys):
    loose = tmp_path / "loose.yaml"
    loose.write_text(FULL.replace("max_decision_flip_rate: 0.15", "max_decision_flip_rate: 1.0"),
                     encoding="utf-8")
    assert gate(str(loose), "jump", points=14, seed=11) == 0
    capsys.readouterr()
    assert gate(str(loose), "jump", points=14, seed=11, fail_on="alarm") == 1
    assert "Blocked by `--fail-on alarm`" in capsys.readouterr().out
    assert latest_alarm([0.0] * 5) is False


def test_a_persistent_second_mode_is_reported_with_its_bound(contract, capsys):
    assert gate(contract, "bimodal", points=26, seed=3) == 0, "the decision never flips"
    out = capsys.readouterr().out
    assert "### Second outcome mode" in out
    assert "refund-basic / repeat_run:" in out and "Wilson 95% lower bound" in out


@pytest.mark.parametrize("contract_text,sut,points,needle", [
    (FULL, "no-such-sim", 3, "unknown sut 'no-such-sim'"),
    (FULL, "json:nope", 3, "cannot load sut 'json:nope'"),
    (FULL, "no_such_module_xyz:thing", 3, "cannot load sut"),
    (FULL, "json:dumps", 3, "has no run(probe_input, t, rng) method"),
    (FULL, "stable", 0, "--points must be at least 1"),
    ("contract: x\nprobes: []", "stable", 3, "cannot load contract"),
    (FULL.replace("[repeat_run, irrelevant_context, reordering, format, paraphrase]", "[paraphrase]")
         .replace("  - field: cited_policy_ids\n    under: [repeat_run]\n"
                  "    relation: jaccard_at_least\n    threshold: 0.85\n", ""),
     "stable", 3, "no executable plan cells"),
])
def test_what_cannot_be_evaluated_exits_2_with_the_reason(tmp_path, capsys, monkeypatch,
                                                          contract_text, sut, points, needle):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    path = tmp_path / "c.yaml"
    path.write_text(contract_text, encoding="utf-8")
    assert gate(str(path), sut, points=points, seed=7) == 2
    assert needle in capsys.readouterr().err


def test_a_missing_contract_file_exits_2(tmp_path, capsys):
    assert gate(str(tmp_path / "absent.yaml"), "stable", points=3, seed=7) == 2
    assert "cannot load contract" in capsys.readouterr().err


SHIPPED = str(__import__("pathlib").Path(__file__).resolve().parent.parent
              / "contracts" / "refund-full-invariants.yaml")


@pytest.mark.parametrize("sut,code", [
    ("policy", 0), ("stable", 0),
    ("distractible", 1), ("order-sensitive", 1), ("format-sensitive", 1), ("non-monotonic", 1),
])
def test_the_shipped_contract_passes_healthy_systems_and_blocks_each_planted_defect(
        sut, code, capsys, monkeypatch):
    """The exact commands .github/workflows/gate.yml runs."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert gate(SHIPPED, sut, points=3, seed=7) == code
    out = capsys.readouterr().out
    assert "| refund-basic | monotonic |" in out
    assert "### Not measured" not in out


class UserSystem:
    """What a team plugs in: their own system behind the three-argument run method."""

    def run(self, probe_input, t, rng):
        return json.dumps({"eligibility_decision": "eligible", "cited_policy_ids": ["POL-7"],
                           "response_wording": "ok"})


USER_INSTANCE = UserSystem()


def test_a_user_system_is_loaded_by_import_path_as_a_class_or_an_instance(contract, capsys):
    module = sys.modules[__name__].__name__
    assert isinstance(resolve_sut(f"{module}:UserSystem"), UserSystem)
    assert resolve_sut(f"{module}:USER_INSTANCE") is USER_INSTANCE
    assert gate(contract, f"{module}:UserSystem", points=2, seed=7) == 0
    out = capsys.readouterr().out
    assert "built-in simulator" not in out
    with pytest.raises(GateConfigError):
        resolve_sut("stable-ish")


def test_the_cli_entry_point_dispatches_gate(contract, monkeypatch, capsys):
    from app import cli

    monkeypatch.setattr(sys, "argv", ["seismo", "gate", "--contract", contract,
                                      "--sut", "format-sensitive", "--points", "2"])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    assert exit_info.value.code == 1
    assert gate_cli.BASELINE_MIN == 8
    assert "## Seismograph gate: BLOCK" in capsys.readouterr().out
