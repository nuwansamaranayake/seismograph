"""Remaining branches of app.checks, app.suite and app.engine.embedding."""
from __future__ import annotations

import json
import math

import httpx
import pytest

from app import checks
from app.checks import (
    CheckOutcome,
    compare_extraction,
    run_assert_check,
    run_grounded_check,
    run_rubric_check,
)
from app.engine import embedding
from app.engine.embedding import HashingEmbedder, OpenRouterEmbedder, cosine
from app.suite import SuiteError, load_suite

REF = {"lagna": "Leo", "moon_nakshatra": "Magha", "moon_pada": 2,
       "mahadasha_lord": "Ketu", "mahadasha_years_remaining": 3.4}


# ---------------------------------------------------------------- checks ---
def test_dig_nested_missing_path_and_non_dict_parent():
    assert checks._dig({"a": {"b": 1}}, "a.b") == (True, 1)
    assert checks._dig({"a": {"b": 1}}, "a.c") == (False, None)
    assert checks._dig({"a": 5}, "a.b") == (False, None)
    assert checks._dig({"a": None}, "a") == (True, None)


def test_numeric_tolerance_failure_modes():
    policy = {"numeric_tolerance": [
        {"field": "x", "reference_field": "x", "tolerance": 0.1}]}
    # missing
    out = run_assert_check("{}", policy, {"x": 1})
    assert not out.passed and "missing or not a number" in out.reasons[0]
    # bool is not a number
    out = run_assert_check('{"x": true}', policy, {"x": 1})
    assert "missing or not a number" in out.reasons[0]
    # string is not a number
    out = run_assert_check('{"x": "1"}', policy, {"x": 1})
    assert "missing or not a number" in out.reasons[0]
    # reference absent
    out = run_assert_check('{"x": 1}', policy, {})
    assert "reference x absent" in out.reasons[0]
    # out of tolerance
    out = run_assert_check('{"x": 2}', policy, {"x": 1})
    assert "differs by 1 > tolerance 0.1" in out.reasons[0]
    # within tolerance passes
    assert run_assert_check('{"x": 1.05}', policy, {"x": 1}).passed


def test_field_equals_missing_mismatch_and_match():
    policy = {"field_equals": [{"field": "a.b", "reference_field": "r"}]}
    out = run_assert_check("{}", policy, {"r": 1})
    assert out.reasons == ["equals[a.b]: field missing"]
    out = run_assert_check('{"a": {"b": 2}}', policy, {"r": 1})
    assert "2 != reference 1" in out.reasons[0]
    assert run_assert_check('{"a": {"b": 1}}', policy, {"r": 1}).passed


def test_non_json_output_is_a_failure_not_an_exception():
    out = run_assert_check("not json", {}, {})
    assert out == CheckOutcome("assert", False, [out.reasons[0]], {})
    assert out.reasons[0].startswith("output is not JSON")


def test_compare_extraction_pada_mismatch_and_clean():
    good = {"lagna": "leo", "moon_nakshatra": "MAGHA", "moon_pada": 2,
            "mahadasha_lord": "Ketu", "mahadasha_years_remaining": 3.5}
    assert compare_extraction(good, REF, 0.25) == []
    bad = dict(good, moon_pada=3)
    assert compare_extraction(bad, REF, 0.25) == [
        "moon_pada: reading states 3, reference is 2"]


def test_compare_extraction_empty_and_wrong_fields():
    ext = {"lagna": "", "moon_nakshatra": "Ashwini", "moon_pada": 2,
           "mahadasha_lord": "Ketu", "mahadasha_years_remaining": -1}
    reasons = compare_extraction(ext, REF, 0.25)
    assert any("lagna: reading states nothing" in r for r in reasons)
    assert any("moon_nakshatra: reading states 'Ashwini'" in r for r in reasons)
    assert any("nothing usable" in r for r in reasons)
    far = dict(ext, lagna="Leo", moon_nakshatra="Magha", mahadasha_years_remaining=9.0)
    assert any("tolerance 0.25" in r for r in compare_extraction(far, REF, 0.25))


class Gw:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def complete(self, *, model, messages, json_schema=None, temperature=0.0):
        self.calls.append((model, json_schema["name"], temperature))
        return self.reply


def test_grounded_check_uses_model_only_to_extract():
    gw = Gw({"lagna": "Leo", "moon_nakshatra": "Magha", "moon_pada": 2,
             "mahadasha_lord": "Ketu", "mahadasha_years_remaining": 3.4})
    out = run_grounded_check(gw, "judge-x", "some reading", REF)
    assert out.passed and out.check_type == "grounded"
    assert gw.calls == [("judge-x", "chart_facts", 0.0)]


@pytest.mark.parametrize("verdict,fragment", [
    ({"score": 5, "evidence": ""}, "quoted nothing"),
    ({"score": 5, "evidence": "invented words"}, "not verbatim"),
    ({"score": 6, "evidence": "ok text"}, "outside the rubric's 1-5 range"),
    ({"score": True, "evidence": "ok text"}, "outside"),
    ({"score": "5", "evidence": "ok text"}, "outside"),
    ({"score": 2, "evidence": "ok text"}, "2 < 4"),
])
def test_rubric_failures(verdict, fragment):
    out = run_rubric_check(Gw(verdict), "m", "an ok   text here")
    assert not out.passed
    assert any(fragment in r for r in out.reasons)


def test_rubric_passes_when_quote_is_rewrapped():
    out = run_rubric_check(Gw({"score": 4, "evidence": "ok text"}), "m", "an ok\n  text here")
    assert out.passed and out.reasons == []


# ----------------------------------------------------------------- suite ---
def _write_suite(root, *, yaml_text=None, cases=True, policy=True):
    root.mkdir(parents=True, exist_ok=True)
    (root / "suite.yaml").write_text(yaml_text or (
        "suite: t\nversion: v1\ntarget:\n  id: tid\n  json_path: a.b\n"
        "layers:\n  engine:\n    check: assert\n    policy: policy/e.json\n"
        "profiles:\n  full:\n    repeats: 2\n"), encoding="utf-8")
    if policy:
        (root / "policy").mkdir(exist_ok=True)
        (root / "policy" / "e.json").write_text("{}", encoding="utf-8")
    if cases:
        (root / "cases").mkdir(exist_ok=True)
        (root / "cases" / "c.json").write_text(json.dumps(
            {"id": "c1", "source": "synthetic", "request": {"q": 1}, "reference": {}}),
            encoding="utf-8")


def test_load_minimal_suite_and_unknown_profile(tmp_path):
    _write_suite(tmp_path / "s")
    suite = load_suite(tmp_path / "s")
    assert suite.target_id == "tid" and suite.json_path == "a.b"
    assert suite.profile("full").repeats == 2 and suite.profile("full").rotate is None
    with pytest.raises(SuiteError, match=r"no profile 'daily' \(have: \['full'\]\)"):
        suite.profile("daily")


def test_target_id_defaults_to_suite_name(tmp_path):
    _write_suite(tmp_path / "s", yaml_text=(
        "suite: nm\nversion: v1\nlayers:\n  e:\n    check: assert\n    policy: policy/e.json\n"
        "profiles:\n  full:\n    repeats: 1\n"))
    suite = load_suite(tmp_path / "s")
    assert suite.target_id == "nm" and suite.json_path is None


def test_missing_policy_file_raises(tmp_path):
    _write_suite(tmp_path / "s", policy=False)
    with pytest.raises(SuiteError, match="missing"):
        load_suite(tmp_path / "s")


def test_malformed_policy_json_raises(tmp_path):
    _write_suite(tmp_path / "s")
    (tmp_path / "s" / "policy" / "e.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(SuiteError, match="e.json"):
        load_suite(tmp_path / "s")


def test_no_layers_no_cases_no_profiles(tmp_path):
    _write_suite(tmp_path / "a", yaml_text="suite: t\nversion: v1\n")
    with pytest.raises(SuiteError, match="no layers declared"):
        load_suite(tmp_path / "a")
    _write_suite(tmp_path / "b", cases=False)
    with pytest.raises(SuiteError, match="no cases"):
        load_suite(tmp_path / "b")
    _write_suite(tmp_path / "c", yaml_text=(
        "suite: t\nversion: v1\nlayers:\n  e:\n    check: assert\n    policy: policy/e.json\n"))
    with pytest.raises(SuiteError, match="no profiles declared"):
        load_suite(tmp_path / "c")


def test_digest_ignores_baseline_dir_and_crlf(tmp_path):
    _write_suite(tmp_path / "s")
    before = load_suite(tmp_path / "s").content_sha256_16()
    (tmp_path / "s" / "baseline").mkdir()
    (tmp_path / "s" / "baseline" / "b.json").write_text("{}", encoding="utf-8")
    assert load_suite(tmp_path / "s").content_sha256_16() == before
    p = tmp_path / "s" / "policy" / "e.json"
    p.write_bytes(b"{}\n")
    lf = load_suite(tmp_path / "s").content_sha256_16()
    p.write_bytes(b"{}\r\n")
    assert load_suite(tmp_path / "s").content_sha256_16() == lf


# ------------------------------------------------------------- embedding ---
def test_hashing_embedder_is_deterministic_and_unit_norm():
    e = HashingEmbedder(dim=32)
    a, b = e.embed(["Hello world", "hello   WORLD!"])
    assert a == b
    assert math.isclose(sum(x * x for x in a), 1.0)
    assert e.embed(["!!!"]) == [[0.0] * 32]  # no tokens: zero vector, not NaN
    assert e.name == "hashing"


def test_cosine_values():
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([0, 0], [1, 1]) == 0.0
    assert cosine([1, 1], [0, 0]) == 0.0
    assert cosine([1, 0], [-1, 0]) == pytest.approx(-1.0)


def test_openrouter_embedder_refuses_blind():
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY is not set"):
        OpenRouterEmbedder("", "m")
    with pytest.raises(RuntimeError, match="EMBEDDING_MODEL is not set"):
        OpenRouterEmbedder("k", "")


def test_openrouter_embedder_posts_and_orders_by_index(monkeypatch):
    seen = {}

    class R:
        def raise_for_status(self):
            seen["checked"] = True

        def json(self):
            return {"data": [{"index": 1, "embedding": [2.0]},
                             {"index": 0, "embedding": [1.0]}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(url=url, headers=headers, json=json, timeout=timeout)
        return R()

    monkeypatch.setattr(embedding.httpx, "post", fake_post)
    e = OpenRouterEmbedder("secret", "emb-1", base_url="https://example.test/api/")
    assert e.embed(["a", "b"]) == [[1.0], [2.0]]
    assert seen["url"] == "https://example.test/api/embeddings"
    assert seen["json"] == {"model": "emb-1", "input": ["a", "b"]}
    assert seen["headers"] == {"Authorization": "Bearer secret"}
    assert seen["timeout"] == 60 and seen["checked"]


def test_openrouter_embedder_propagates_http_errors(monkeypatch):
    def fake_post(url, **kw):
        return httpx.Response(500, request=httpx.Request("POST", url))

    monkeypatch.setattr(embedding.httpx, "post", fake_post)
    with pytest.raises(httpx.HTTPStatusError):
        OpenRouterEmbedder("k", "m").embed(["x"])
