"""Pick the judge model from the LIVE provider list, smallest that clears the floor.

docs/gates-spec.md g2 forbids picking a model id from memory. So this reads
https://openrouter.ai/api/v1/models at run time, ranks the eligible models
smallest-first, and walks the ranking until one clears the agreement floor on
data/checks/judge_agreement_set.v1.json. The first one that clears wins — not
the best one, the smallest one that is good enough, because a judge is run
thousands of times and the cheapest adequate judge is the one you can afford to
run on every request.

"Smallest" is measured by prompt price. OpenRouter publishes no parameter count,
so price per token is the only size proxy the API actually carries; it tracks
size closely enough within a generation and it is the quantity that decides
whether this check can run in production. That substitution is recorded in the
report header rather than hidden.

The agreement set is disjoint from the three measured sets. Selecting on the
same samples the checks are later scored against would turn the sensitivity
numbers into a description of the selection.

Writes SEISMO_JUDGE_MODEL into .env and prints SELECTION_JSON for the gate.

  python scripts/judge_select.py            # select and write .env
  python scripts/judge_select.py --dry-run  # select, print, write nothing
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.checks import extract_chart_facts, score_against_rubric  # noqa: E402
from app.engine.golden import wilson  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SETS = ROOT / "data" / "checks"
MODELS_URL = "https://openrouter.ai/api/v1/models"

# The floor. A judge that agrees with the human labels less often than this is
# not a measuring instrument. Set here, before any model is tried, and never
# lowered to make a candidate fit (docs/gates-spec.md g2).
AGREEMENT_FLOOR = 0.85
MAX_CANDIDATES = 8          # budget guard: 8 x 20 = 160 judge calls worst case
MIN_CONTEXT = 16384


def eligible(model: dict) -> tuple[bool, str]:
    """Filters, each with a reason that goes in the report."""
    mid = model["id"]
    if mid.startswith("~"):
        return False, "floating alias, not a pinned id"
    if mid.endswith(":free"):
        return False, "free tier is rate-limited, unusable as a production judge"
    if mid.endswith(":batch"):
        return False, "batch endpoint is asynchronous, unusable as a synchronous judge"
    params = model.get("supported_parameters") or []
    if "structured_outputs" not in params:
        return False, "no structured output support"
    arch = model.get("architecture") or {}
    if "text" not in (arch.get("input_modalities") or []):
        return False, "does not take text input"
    if "text" not in (arch.get("output_modalities") or []):
        return False, "does not emit text"
    if (model.get("context_length") or 0) < MIN_CONTEXT:
        return False, f"context {model.get('context_length')} < {MIN_CONTEXT}"
    try:
        if float(model["pricing"]["prompt"]) <= 0:
            return False, "zero prompt price, i.e. a free variant"
    except (KeyError, TypeError, ValueError):
        return False, "no usable prompt price"
    return True, "eligible"


def rank(models: list[dict]) -> list[dict]:
    keep = [m for m in models if eligible(m)[0]]
    keep.sort(key=lambda m: (float(m["pricing"]["prompt"]),
                             float(m["pricing"].get("completion") or 0),
                             m["id"]))
    return keep


def fetch_models() -> list[dict]:
    r = httpx.get(MODELS_URL, timeout=30.0)
    r.raise_for_status()
    return r.json()["data"]


def preflight(key: str) -> tuple[bool, str]:
    """Is the key actually good, before spending 160 calls discovering it is not?

    The model list is unauthenticated, so it succeeds with a revoked key and the
    first real failure would otherwise be a wall of identical 401s attributed to
    eight innocent models. One introspection call separates "no model is good
    enough" from "this credential is dead".
    """
    try:
        r = httpx.get("https://openrouter.ai/api/v1/key",
                      headers={"Authorization": f"Bearer {key}"}, timeout=20.0)
    except httpx.HTTPError as exc:
        return False, f"cannot reach the provider: {type(exc).__name__}: {exc}"
    if r.status_code == 200:
        data = r.json().get("data", {})
        return True, (f"key accepted (limit={data.get('limit')} usage={data.get('usage')} "
                      f"free_tier={data.get('is_free_tier')})")
    message = ""
    try:
        message = r.json().get("error", {}).get("message", "")
    except ValueError:
        message = r.text[:120]
    return False, f"provider rejected OPENROUTER_API_KEY: HTTP {r.status_code} {message!r}"


def _norm(text: object) -> str:
    return "".join(ch for ch in str(text).lower() if ch.isalpha())


def score_candidate(gateway, model_id: str, items: list[dict]) -> dict:
    """Run one candidate over the agreement set. Returns agreement + per-item log."""
    agreed, log, calls, errors = 0, [], 0, 0
    for item in items:
        try:
            if item["mode"] == "extraction":
                got = extract_chart_facts(gateway, model_id, item["output"])
                calls += 1
                gold = item["gold"]
                ok = (
                    _norm(got.get("lagna")) == _norm(gold["lagna"])
                    and _norm(got.get("moon_nakshatra")) == _norm(gold["moon_nakshatra"])
                    and got.get("moon_pada") == gold["moon_pada"]
                    and _norm(got.get("mahadasha_lord")) == _norm(gold["mahadasha_lord"])
                    and isinstance(got.get("mahadasha_years_remaining"), (int, float))
                    and abs(float(got["mahadasha_years_remaining"])
                            - float(gold["mahadasha_years_remaining"])) <= 0.01
                )
                detail = got
            else:
                verdict = score_against_rubric(gateway, model_id, item["output"])
                calls += 1
                score = verdict.get("score")
                predicted = "clean" if isinstance(score, int) and score >= 4 else "planted"
                ok = predicted == item["gold_label"]
                detail = verdict
        except Exception as exc:                      # provider refusal, timeout, bad JSON
            errors += 1
            ok, detail = False, {"error": f"{type(exc).__name__}: {exc}"[:200]}
        agreed += int(ok)
        log.append({"id": item["id"], "agreed": ok, "detail": detail})
    point, lo, hi = wilson(agreed, len(items))
    return {"model": model_id, "agreed": agreed, "n": len(items),
            "agreement": point, "wilson_lo": lo, "wilson_hi": hi,
            "calls": calls, "errors": errors, "log": log}


def write_env(model_id: str) -> None:
    """Set SEISMO_JUDGE_MODEL in .env, replacing any existing line."""
    env = ROOT / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    out, replaced = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == "SEISMO_JUDGE_MODEL":
            out.append(f"SEISMO_JUDGE_MODEL={model_id}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"SEISMO_JUDGE_MODEL={model_id}")
    env.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    from groundwork import BaseConfig, LLMGateway

    dry_run = "--dry-run" in sys.argv
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        print("judge_select: OPENROUTER_API_KEY missing. Refusing to run blind.")
        return 2

    agreement = json.loads((SETS / "judge_agreement_set.v1.json").read_text(encoding="utf-8"))
    items = agreement["items"]

    ok, detail = preflight(key)
    print(f"judge_select: preflight — {detail}")
    if not ok:
        print("SELECTION_JSON " + json.dumps({
            "chosen": None, "blocked": detail, "agreement_floor": AGREEMENT_FLOOR,
            "agreement_set_sha": agreement["content_sha256_16"],
            "agreement_set_n": len(items), "candidates_considered": 0,
            "candidates_tried": 0, "judge_calls": 0, "attempts": [],
        }))
        return 1

    models = fetch_models()
    ranked = rank(models)
    print(f"judge_select: provider listed {len(models)} models, {len(ranked)} eligible")
    print(f"judge_select: floor={AGREEMENT_FLOOR} on {len(items)} labelled items "
          f"(set sha={agreement['content_sha256_16']})")

    gateway = LLMGateway(BaseConfig(openrouter_api_key=key))
    attempts, chosen, total_calls = [], None, 0
    for model in ranked[:MAX_CANDIDATES]:
        result = score_candidate(gateway, model["id"], items)
        total_calls += result["calls"]
        result["prompt_price"] = model["pricing"]["prompt"]
        result["context_length"] = model.get("context_length")
        attempts.append({k: v for k, v in result.items() if k != "log"})
        print(f"  {model['id']:<48} agreement={result['agreement']:.2f} "
              f"({result['agreed']}/{result['n']}) errors={result['errors']} "
              f"price={model['pricing']['prompt']}")
        if result["agreement"] >= AGREEMENT_FLOOR:
            chosen = result
            break

    selection = {
        "chosen": chosen["model"] if chosen else None,
        "agreement": chosen["agreement"] if chosen else None,
        "agreement_floor": AGREEMENT_FLOOR,
        "agreement_set_sha": agreement["content_sha256_16"],
        "agreement_set_n": len(items),
        "candidates_considered": len(ranked),
        "candidates_tried": len(attempts),
        "size_proxy": "prompt price per token (provider publishes no parameter count)",
        "judge_calls": total_calls,
        "attempts": attempts,
    }
    if not chosen:
        print(f"judge_select: no model in the first {len(attempts)} cleared "
              f"{AGREEMENT_FLOOR}. NOT lowering the floor.")
        print("SELECTION_JSON " + json.dumps(selection))
        return 1

    if not dry_run:
        write_env(chosen["model"])
        print(f"judge_select: wrote SEISMO_JUDGE_MODEL={chosen['model']} to .env")
    print("SELECTION_JSON " + json.dumps(selection))
    return 0


if __name__ == "__main__":
    sys.exit(main())
