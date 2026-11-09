"""app.cli: run(), run_suite_cli(), the Jev wrappers and main() dispatch.

Environment is controlled explicitly: every variable the CLI or the code it
calls reads is set or removed per test, so the registry hydration in
app.jev_runner and the operator's shell cannot change a result.
"""
from __future__ import annotations

import json
import runpy
import sys
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from app import cli, db
from app.engine.suts import DEMO_SUTS, StableSUT
from app.runner import header_for, write_baseline
from app.suite import load_suite
from app.targets import CallRecord, TargetConfigError, TargetError

ENV_VARS = (
    "SEISMO_TARGET_ADAPTER", "SEISMO_JUDGE_MODEL", "SEISMO_REPORT_URL", "CALCULATOR_MCP_URL",
    "RESEND_API_KEY", "TYPESAFE_API_KEY", "TYPESAFE_BASE_URL",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# ============================================================ cli.run() ====
def _contract_yaml(tmp_path, *, under="repeat_run", gate="{max_decision_flip_rate: 0.01}",
                   jaccard=False):
    inv = [f"  - {{field: eligibility_decision, under: [{under}], relation: equal}}"]
    if jaccard:
        inv.append("  - {field: cited_policy_ids, under: [repeat_run], "
                   "relation: jaccard_at_least, threshold: 0.9}")
    text = (
        "contract: cov-c\nsubject: s\ninvariants:\n" + "\n".join(inv) + "\n"
        "allowed_variation:\n  - {field: response_wording, rule: semantically_equivalent}\n"
        "run_policy: {samples: 10, configs: 1, confidence: 0.95}\n"
        f"gate: {gate}\n"
        "probes:\n  - {id: p1, input: \"Is this refund eligible? Please say.\"}\n"
    )
    path = tmp_path / "c.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_run_unknown_sut_exits_2(tmp_path, capsys):
    assert cli.run(_contract_yaml(tmp_path), "nope", 3, 1, None) == 2
    err = capsys.readouterr().err
    assert "unknown sut 'nope'" in err and "stable" in err


def test_run_paraphrase_only_contract_fails_loud(tmp_path, capsys):
    path = _contract_yaml(tmp_path, under="paraphrase")
    assert cli.run(path, "stable", 3, 1, None) == 2
    assert "no executable plan cells" in capsys.readouterr().err


def test_run_stable_passes_warmup_message_and_writes_report(tmp_path, capsys):
    report = tmp_path / "out.md"
    code = cli.run(_contract_yaml(tmp_path), "stable", 5, 7, str(report))
    out = capsys.readouterr().out
    assert code == 0
    assert "**PASS**" in out and "control chart warms up after 8 points; have 5" in out
    assert "latest worst flip rate: 0.0000  (gate threshold 0.01)" in out
    assert "sut `stable` | points 5 | seed 7" in out
    assert report.read_text(encoding="utf-8") == out.rstrip("\n") + "\n" or \
        report.read_text(encoding="utf-8").startswith("# Seismograph report — cov-c")
    assert "\r" not in report.read_text(encoding="utf-8")


def test_run_chart_rows_once_baseline_is_full(tmp_path, capsys):
    code = cli.run(_contract_yaml(tmp_path), "stable", 11, 7, None)
    out = capsys.readouterr().out
    assert code == 0
    rows = [ln for ln in out.splitlines() if ln.startswith("| ") and ln[2].isdigit()]
    assert [r.split("|")[1].strip() for r in rows] == ["8", "9", "10"]
    assert "| t | value | ucl | alarm |" in out


def test_run_jump_sut_blocks_after_onset(tmp_path, capsys):
    code = cli.run(_contract_yaml(tmp_path), "jump", 20, 7, None)
    out = capsys.readouterr().out
    assert code == 1 and "**BLOCK**" in out
    assert any(ln.split("|")[-2].strip() not in ("-", "") for ln in out.splitlines()
               if ln.startswith("| 1") or ln.startswith("| 2")), "an alarm rule is named"


class _RaggedPolicySUT:
    """Cites a different policy id on every call, so pairwise jaccard is 0."""

    name = "ragged"

    def __init__(self):
        self.n = 0

    def run(self, probe_input, t, rng):
        self.n += 1
        return json.dumps({"eligibility_decision": "eligible", "cited_policy_ids": [f"P{self.n}"],
                           "response_wording": "same"})


def test_run_jaccard_failure_blocks_and_is_reported(tmp_path, capsys, monkeypatch):
    monkeypatch.setitem(DEMO_SUTS, "ragged", _RaggedPolicySUT())
    code = cli.run(_contract_yaml(tmp_path, jaccard=True), "ragged", 3, 1, None)
    out = capsys.readouterr().out
    assert code == 1
    assert "jaccard invariant FAILED: probe `p1` field `cited_policy_ids` mean 0.0000 < " \
           "declared threshold 0.9" in out


class _MalformedSUT:
    name = "malformed"

    def run(self, probe_input, t, rng):
        return "this is not json"


def test_run_malformed_output_blocks(tmp_path, capsys, monkeypatch):
    monkeypatch.setitem(DEMO_SUTS, "malformed", _MalformedSUT())
    code = cli.run(_contract_yaml(tmp_path), "malformed", 2, 1, None)
    out = capsys.readouterr().out
    assert code == 1 and "latest malformed rate: 1.0000" in out and "**BLOCK**" in out


# ====================================================== run_suite_cli() ====
SUITE_YAML = """suite: cov
version: v1
target: {id: cov-target}
layers:
  policy:
    check: assert
    policy: policy/policy.json
profiles:
  full: {repeats: 1}
"""


@pytest.fixture
def suites_dir(tmp_path):
    root = tmp_path / "suites" / "cov"
    (root / "policy").mkdir(parents=True)
    (root / "cases").mkdir()
    (root / "suite.yaml").write_text(SUITE_YAML, encoding="utf-8")
    (root / "policy" / "policy.json").write_text(
        json.dumps({"regex_absent": [{"name": "forbidden", "pattern": "FORBIDDEN"}]}),
        encoding="utf-8")
    for cid, text in (("a", "all fine"), ("b", "also fine")):
        (root / "cases" / f"{cid}.json").write_text(json.dumps(
            {"id": cid, "source": "synthetic", "request": {"text": text}, "reference": {}}),
            encoding="utf-8")
    return tmp_path / "suites"


class EchoTarget:
    """Returns the request text; a case whose text contains FORBIDDEN will fail the policy."""

    def __init__(self, target_id="cov-target"):
        self.target_id = target_id
        self.calls = 0

    def call(self, body, json_path=None):
        self.calls += 1
        return CallRecord(self.target_id, "http", "POST /", "h", 1,
                          raw_response={"text": body["text"]})


@pytest.fixture
def echo(monkeypatch):
    seen = {}

    def from_env(target_id):
        seen["target_id"] = target_id
        return EchoTarget(target_id)

    monkeypatch.setattr("app.targets.HttpTarget.from_env", staticmethod(from_env))
    return seen


def _make_case_fail(suites_dir):
    p = suites_dir / "cov" / "cases" / "b.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["request"]["text"] = "FORBIDDEN"
    p.write_text(json.dumps(data), encoding="utf-8")


def _g4(out: str) -> dict:
    line = next(ln for ln in out.splitlines() if ln.startswith("G4_RUN "))
    return json.loads(line[len("G4_RUN "):])


def _run(suites_dir, **kw):
    args = dict(suite_name="cov", profile_name="full", fail_on="drift",
                suites_dir=str(suites_dir), report_path=None, write_baseline_flag=False,
                store=False, alert=True)
    args.update(kw)
    return cli.run_suite_cli(**args)


def test_clean_suite_run_exits_zero_without_alert(suites_dir, echo, capsys, monkeypatch):
    monkeypatch.setattr("app.alerts.send_alert",
                        lambda *a, **k: pytest.fail("no alert on a clean run"))
    assert _run(suites_dir) == 0
    g4 = _g4(capsys.readouterr().out)
    assert g4["exit_code"] == 0 and g4["checks"] == 2 and g4["failures"] == []
    assert g4["alert_message_id"] is None and g4["target_id"] == "cov-target"
    assert echo["target_id"] == "cov-target"
    assert set(g4["unbaselined"]) == {"a::policy", "b::policy"}


def test_target_id_override_selects_env_prefix(suites_dir, echo, capsys):
    assert _run(suites_dir, target_id="other-t") == 0
    assert echo["target_id"] == "other-t"
    assert _g4(capsys.readouterr().out)["target_id"] == "other-t"


def test_failure_sends_one_alert_with_report_link(suites_dir, echo, capsys, monkeypatch, tmp_path):
    _make_case_fail(suites_dir)
    sent = []
    monkeypatch.setattr("app.alerts.send_alert",
                        lambda subject, body: sent.append((subject, body)) or "msg_42")
    report = tmp_path / "nested" / "r.md"
    assert _run(suites_dir, report_path=str(report)) == 1
    out = capsys.readouterr().out
    g4 = _g4(out)
    assert g4["exit_code"] == 1 and g4["failures"] == ["b::policy"]
    assert g4["alert_message_id"] == "msg_42" and "alert sent: resend message id msg_42" in out
    (subject, body), = sent
    assert subject == "[seismograph] cov/full: 1 failed, 0 drifted, 0 incomplete"
    assert f"Report: {report}" in body and "- b / policy (assert): forbidden[forbidden]" in body
    assert report.read_text(encoding="utf-8").startswith("# Seismograph suite run — cov / full")


def test_report_url_env_overrides_link_and_missing_report_is_stated(
        suites_dir, echo, monkeypatch):
    _make_case_fail(suites_dir)
    sent = []
    monkeypatch.setattr("app.alerts.send_alert", lambda s, b: sent.append(b) or "m")
    _run(suites_dir)
    assert "Report: (no report file written; pass --report)" in sent[0]
    monkeypatch.setenv("SEISMO_REPORT_URL", " https://reports.example/r ")
    _run(suites_dir)
    assert "Report: https://reports.example/r" in sent[1]


def test_alert_failure_is_reported_not_swallowed(suites_dir, echo, capsys, monkeypatch):
    from app.alerts import AlertError

    _make_case_fail(suites_dir)

    def boom(subject, body):
        raise AlertError("resend down")

    monkeypatch.setattr("app.alerts.send_alert", boom)
    assert _run(suites_dir) == 1
    cap = capsys.readouterr()
    assert "ALERT FAILED: resend down" in cap.err
    g4 = _g4(cap.out)
    assert g4["alert_error"] == "resend down" and g4["alert_message_id"] is None


def test_no_alert_flag_skips_send(suites_dir, echo, monkeypatch):
    _make_case_fail(suites_dir)
    monkeypatch.setattr("app.alerts.send_alert",
                        lambda *a, **k: pytest.fail("alert disabled"))
    assert _run(suites_dir, alert=False) == 1


def test_write_baseline_then_regression_is_drift(suites_dir, echo, capsys, monkeypatch):
    assert _run(suites_dir, write_baseline_flag=True) == 0
    baseline = suites_dir / "cov" / "baseline" / "cov-target.json"
    assert baseline.exists() and "baseline written:" in capsys.readouterr().out
    assert json.loads(baseline.read_text(encoding="utf-8"))["verdicts"] == {
        "a::policy": True, "b::policy": True}
    _make_case_fail(suites_dir)   # suite digest ignores baseline/, but cases changed:
    # the digest covers cases, so the committed baseline is now refused, not compared
    assert _run(suites_dir, alert=False) == 2
    assert "baseline refused" in capsys.readouterr().err


def test_drift_against_matching_baseline(suites_dir, capsys, monkeypatch):
    from datetime import date

    from app.runner import run_suite

    suite = load_suite(suites_dir / "cov")
    ok = run_suite(suite, EchoTarget(), suite.profile("full"), on=date(2026, 1, 1))
    write_baseline(suites_dir / "cov" / "baseline" / "cov-target.json", ok)

    class Bad(EchoTarget):
        def call(self, body, json_path=None):
            return CallRecord(self.target_id, "http", "POST /", "h", 1,
                              raw_response={"text": "FORBIDDEN"})

    monkeypatch.setattr("app.targets.HttpTarget.from_env", staticmethod(lambda tid: Bad(tid)))
    code = _run(suites_dir, alert=False, fail_on="check")
    g4 = _g4(capsys.readouterr().out)
    assert code == 1 and sorted(g4["drifted"]) == ["a::policy", "b::policy"]
    assert g4["unbaselined"] == []


def test_baseline_header_mismatch_exits_2(suites_dir, echo, capsys):
    suite = load_suite(suites_dir / "cov")
    profile = suite.profile("full")
    header = header_for(suite, profile, "cov-target", None, False)
    path = suites_dir / "cov" / "baseline" / "cov-target.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"header": dict(header, suite_version="v0"), "verdicts": {}}),
                    encoding="utf-8")
    assert _run(suites_dir) == 2
    assert "baseline refused: baseline cov-target.json header mismatch on ['suite_version']" \
        in capsys.readouterr().err


def test_missing_suite_and_missing_profile_are_config_errors(suites_dir, echo, capsys):
    assert _run(suites_dir, suite_name="absent") == 2
    assert "configuration error: no suite.yaml" in capsys.readouterr().err
    assert _run(suites_dir, profile_name="nightly") == 2
    assert "no profile 'nightly'" in capsys.readouterr().err


def test_http_target_config_error_exits_2(suites_dir, monkeypatch, capsys):
    def from_env(tid):
        raise TargetConfigError("SEISMO_TARGET_COV_TARGET_URL is not set")

    monkeypatch.setattr("app.targets.HttpTarget.from_env", staticmethod(from_env))
    assert _run(suites_dir) == 2
    assert "configuration error: SEISMO_TARGET_COV_TARGET_URL is not set" in capsys.readouterr().err


def test_unknown_adapter_exits_2_and_mcp_adapter_is_selected(suites_dir, monkeypatch, capsys):
    monkeypatch.setenv("SEISMO_TARGET_ADAPTER", "carrier-pigeon")
    assert _run(suites_dir) == 2
    assert "unknown SEISMO_TARGET_ADAPTER 'carrier-pigeon'; use http or mcp" in \
        capsys.readouterr().err
    chosen = {}

    def mcp_from_env(tid, url_var):
        chosen.update(tid=tid, url_var=url_var)
        return EchoTarget(tid)

    monkeypatch.setenv("SEISMO_TARGET_ADAPTER", " MCP ")
    monkeypatch.setattr("app.targets.McpTarget.from_env", staticmethod(mcp_from_env))
    assert _run(suites_dir) == 0
    assert chosen == {"tid": "cov-target", "url_var": "CALCULATOR_MCP_URL"}


def test_store_flag_persists_calls(suites_dir, echo, monkeypatch):
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool)
    db.metadata.create_all(engine)
    db.set_engine_for_tests(engine)
    session = db.get_session()
    monkeypatch.setattr("app.db.get_session", lambda: session)
    assert _run(suites_dir, store=True) == 0
    assert session.execute(sa.text("select count(*) from target_calls")).scalar() == 2


def test_judge_model_builds_gateway_and_runs_rubric_layer(suites_dir, echo, capsys, monkeypatch):
    root = suites_dir / "cov"
    (root / "suite.yaml").write_text(
        SUITE_YAML.replace("profiles:", "  quality:\n    check: rubric\n    policy: policy/policy.json\nprofiles:"),
        encoding="utf-8")
    made = []

    class FakeGateway:
        def __init__(self):
            made.append(self)

        def complete(self, *, model, messages, json_schema=None, temperature=0.0):
            self.model = model
            return {"score": 5, "evidence": "fine"}

    monkeypatch.setattr("groundwork.gateway.LLMGateway", FakeGateway)
    monkeypatch.setenv("SEISMO_JUDGE_MODEL", " judge-x ")
    assert _run(suites_dir) == 0
    g4 = _g4(capsys.readouterr().out)
    assert g4["header"]["judge_model"] == "judge-x" and g4["checks"] == 4
    assert made and made[0].model == "judge-x"


def test_missing_judge_marks_run_incomplete_and_fails(suites_dir, echo, capsys):
    root = suites_dir / "cov"
    (root / "suite.yaml").write_text(
        SUITE_YAML.replace("profiles:", "  quality:\n    check: rubric\n    policy: policy/policy.json\nprofiles:"),
        encoding="utf-8")
    assert _run(suites_dir, alert=False) == 1
    g4 = _g4(capsys.readouterr().out)
    assert len(g4["incomplete"]) == 2 and "SEISMO_JUDGE_MODEL is unset" in g4["incomplete"][0]


def test_alert_body_truncates_and_lists_everything():
    from app.runner import LayerOutcome, RunResult

    r = RunResult("s", "p", "t", {})
    r.outcomes = [LayerOutcome(f"c{i}", "L", "assert", False, ["r" * 300]) for i in range(12)]
    r.drifted = [f"k{i}" for i in range(12)]
    r.incomplete = [f"inc{i}" for i in range(12)]
    body = cli._alert_body(r, "LINK")
    assert "failed checks : 12" in body and "Report: LINK" in body
    assert body.count("\n- c") == 10 and body.count("- drift: k") == 10
    assert body.count("- incomplete: inc") == 10
    assert "r" * 201 not in body


# ================================================== jev wrappers & main ====
def test_jev_contract_errors_exit_2(tmp_path, capsys):
    with pytest.raises(SystemExit) as ei:
        cli._jev_contract(str(tmp_path / "nope"))
    assert ei.value.code == 2
    assert "contract error: contract not found" in capsys.readouterr().err
    bad = tmp_path / "bad.yaml"
    bad.write_text("contract: x\n", encoding="utf-8")
    with pytest.raises(SystemExit) as ei:
        cli._jev_contract(str(bad))
    assert ei.value.code == 2 and "contract error:" in capsys.readouterr().err


def test_jev_contract_resolves_a_real_contract(capsys):
    """The Kalika golden set is private and is not in the public repository. Where it is
    present the contract resolves. Where it is absent the CLI must refuse by name with
    exit 2, never run on an empty set. Both are the documented behaviour."""
    from pathlib import Path

    golden = Path("contracts") / "golden" / "kalika-qa-gate.jsonl"
    if golden.is_file():
        contract, path = cli._jev_contract("kalika-qa-gate")
        assert contract.contract == "kalika-qa-gate" and path.name == "kalika-qa-gate.yaml"
    else:
        with pytest.raises(SystemExit) as exit_info:
            cli._jev_contract("kalika-qa-gate")
        assert exit_info.value.code == 2
        assert "golden set missing" in capsys.readouterr().err


C = SimpleNamespace(contract="c1")


@pytest.mark.parametrize("fn_name,call,patched", [
    ("run_jev_cli", lambda: cli.run_jev_cli(C, 3, "rep"), "run_contract"),
    ("calibrate_cli", lambda: cli.calibrate_cli(C, 3, "rep"), "calibrate"),
    ("drift_cli", lambda: cli.drift_cli(C, "ma", "mb", 3, "rep"), "drift"),
])
def test_jev_wrappers_map_errors_to_exit_codes(monkeypatch, capsys, fn_name, call, patched):
    import app.jev_runner as jr

    for exc, code, stream, text in (
        (TargetConfigError("TYPESAFE_API_KEY missing"), 2, "err", "configuration error: TYPESAFE_API_KEY"),
        (jr.RunError("budget"), 1, "err", "FAIL: budget"),
        (TargetError("HTTP 500"), 1, "err", "FAIL: HTTP 500"),
    ):
        def boom(*a, _exc=exc, **k):
            raise _exc

        monkeypatch.setattr(jr, patched, boom)
        assert call() == code
        assert text in getattr(capsys.readouterr(), stream)


def test_run_jev_cli_gate_pass_and_block(monkeypatch, capsys):
    import app.jev_runner as jr

    seen = {}

    def fake(contract, workers, reports_dir):
        seen.update(workers=workers, reports_dir=reports_dir)
        return {"passed": seen["passed"], "metric": 1}

    monkeypatch.setattr(jr, "run_contract", fake)
    seen["passed"] = True
    assert cli.run_jev_cli(C, 5, "R") == 0
    assert "GATE PASS: c1" in capsys.readouterr().out and seen == {
        "workers": 5, "reports_dir": "R", "passed": True}
    seen["passed"] = False
    assert cli.run_jev_cli(C, 5, "R") == 1
    assert "GATE BLOCK: c1" in capsys.readouterr().out


def test_calibrate_and_drift_cli_print_result(monkeypatch, capsys):
    import app.jev_runner as jr

    monkeypatch.setattr(jr, "calibrate", lambda c, workers, reports_dir: {"ece": 0.01})
    monkeypatch.setattr(jr, "drift", lambda c, a, b, workers, reports_dir: {"pair": [a, b]})
    assert cli.calibrate_cli(C, 1, "r") == 0
    assert json.loads(capsys.readouterr().out) == {"ece": 0.01}
    assert cli.drift_cli(C, "ma", "mb", 1, "r") == 0
    assert json.loads(capsys.readouterr().out) == {"pair": ["ma", "mb"]}


# ------------------------------------------------------------------ main ----
def _main(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["seismo", *argv])
    with pytest.raises(SystemExit) as ei:
        cli.main()
    return ei.value.code


def test_main_calibrate_and_drift_dispatch(monkeypatch):
    monkeypatch.setattr(cli, "_jev_contract", lambda arg: (C, "p"))
    monkeypatch.setattr(cli, "calibrate_cli", lambda c, w, r: 11)
    monkeypatch.setattr(cli, "drift_cli", lambda c, a, b, w, r: 12)
    assert _main(monkeypatch, "calibrate", "--contract", "x", "--workers", "2") == 11
    assert _main(monkeypatch, "drift", "--contract", "x", "--model-a", "a", "--model-b", "b") == 12


def test_main_passes_arguments_through(monkeypatch):
    got = {}
    monkeypatch.setattr(cli, "_jev_contract", lambda arg: (C, "p"))

    def cal(c, w, r):
        got["cal"] = (w, r)
        return 0

    def drift(c, a, b, w, r):
        got["drift"] = (a, b, w, r)
        return 0

    monkeypatch.setattr(cli, "calibrate_cli", cal)
    monkeypatch.setattr(cli, "drift_cli", drift)
    _main(monkeypatch, "calibrate", "--contract", "x", "--reports-dir", "RD")
    _main(monkeypatch, "drift", "--contract", "x", "--model-a", "A", "--model-b", "B",
          "--workers", "4")
    assert got == {"cal": (8, "RD"), "drift": ("A", "B", 4, "reports")}


def test_main_requires_exactly_one_of_contract_or_suite(monkeypatch, capsys):
    assert _main(monkeypatch, "run") == 2
    assert "pass exactly one of --contract or --suite" in capsys.readouterr().err
    assert _main(monkeypatch, "run", "--contract", "a", "--suite", "b") == 2


def test_main_suite_dispatch_passes_every_flag(monkeypatch):
    got = {}

    def fake(*args):
        got["args"] = args
        return 7

    monkeypatch.setattr(cli, "run_suite_cli", fake)
    code = _main(monkeypatch, "run", "--suite", "kalika", "--profile", "full", "--fail-on",
                 "check", "--suites-dir", "S", "--report", "R.md", "--write-baseline",
                 "--store", "--no-alert", "--target-id", "tid")
    assert code == 7
    assert got["args"] == ("kalika", "full", "check", "S", "R.md", True, True, False, "tid")
    _main(monkeypatch, "run", "--suite", "kalika")
    assert got["args"] == ("kalika", "daily", "drift", "suites", None, False, False, True, None)


def test_main_contract_dispatch_jev_and_demo(monkeypatch):
    jev_contract = SimpleNamespace(sut=SimpleNamespace(adapter="jev"))
    monkeypatch.setattr(cli, "_jev_contract", lambda arg: (jev_contract, "p.yaml"))
    monkeypatch.setattr(cli, "run_jev_cli", lambda c, w, r: 21 if c is jev_contract else 99)
    assert _main(monkeypatch, "run", "--contract", "x") == 21

    demo = SimpleNamespace(sut=None)
    monkeypatch.setattr(cli, "_jev_contract", lambda arg: (demo, "p.yaml"))
    got = {}

    def fake_run(path, sut, points, seed, report):
        got["args"] = (path, sut, points, seed, report)
        return 5

    monkeypatch.setattr(cli, "run", fake_run)
    assert _main(monkeypatch, "run", "--contract", "x") == 5
    assert got["args"] == ("p.yaml", "stable", 12, 7, None)
    _main(monkeypatch, "run", "--contract", "x", "--sut", "jump", "--points", "3",
          "--seed", "9", "--report", "o.md")
    assert got["args"] == ("p.yaml", "jump", 3, 9, "o.md")


def test_module_entrypoint_runs_main(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["seismo", "run"])
    with pytest.raises(SystemExit) as ei:
        runpy.run_module("app.cli", run_name="__main__")
    assert ei.value.code == 2
    assert "pass exactly one of" in capsys.readouterr().err


def test_demo_suts_include_stable():
    assert isinstance(DEMO_SUTS["stable"], StableSUT)


def test_run_passing_jaccard_invariant_does_not_block(tmp_path, capsys):
    code = cli.run(_contract_yaml(tmp_path, jaccard=True), "stable", 3, 1, None)
    out = capsys.readouterr().out
    assert code == 0 and "jaccard invariant FAILED" not in out


def test_run_contract_with_only_a_jaccard_invariant(tmp_path, capsys):
    path = tmp_path / "j.yaml"
    path.write_text(
        "contract: j-only\nsubject: s\ninvariants:\n"
        "  - {field: cited_policy_ids, under: [repeat_run], relation: jaccard_at_least, "
        "threshold: 0.9}\n"
        "run_policy: {samples: 10, configs: 1, confidence: 0.95}\n"
        "gate: {max_decision_flip_rate: 0.01}\n"
        "probes:\n  - {id: p1, input: \"Is this refund eligible? Please say.\"}\n",
        encoding="utf-8")
    assert cli.run(str(path), "stable", 2, 1, None) == 0
    assert "latest worst flip rate: 0.0000" in capsys.readouterr().out
