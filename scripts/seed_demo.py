"""Record the guide's walkthrough on a running instance, through the public API.

    python scripts/seed_demo.py            # against http://127.0.0.1:8765

Every system here is a built-in SIMULATOR with a defect planted on purpose, and every
judge is a simulated judge whose verdicts are derived from the anchor labels. Nothing
this script records is a measurement of a real system. It exists so a new user can see
each view of the dashboard with a known defect on it, and so the guide's screenshots
are reproducible: same seeds, same charts.

It only calls documented endpoints, the same ones the dashboard calls. It refuses to
run against a non-development instance.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
BASE = f"http://{os.getenv('API_HOST', '127.0.0.1')}:{os.getenv('API_PORT', '8765')}"
TOKEN = os.getenv("SMOKE_TEST_TOKEN", "")
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
TEMPLATE = (REPO / "contracts" / "refund-full-invariants.yaml").read_text(encoding="utf-8")

# (contract name, simulator, runs, seed, why it is in the walkthrough)
SCENARIOS = [
    ("refund-agent", "jump", 20, 11, "the flip rate jumps at run 12: the chart signals"),
    ("returns-router", "bimodal", 28, 3, "a second outcome mode the flip rate cannot see"),
    ("intake-parser", "format-sensitive", 3, 7, "one violated cell in the invariant matrix"),
    ("policy-baseline", "policy", 12, 7, "a healthy system: every invariant holds"),
]


def contract_yaml(name: str) -> str:
    """The shipped full-invariant contract under another name, with a tolerance wide
    enough that the simulators' 4% background noise passes and a planted defect does not."""
    return (TEMPLATE
            .replace("contract: refund-full-invariants", f"contract: {name}")
            .replace("samples: 20", "samples: 40")
            .replace("max_decision_flip_rate: 0.10", "max_decision_flip_rate: 0.20"))


def call(client: httpx.Client, method: str, path: str, body: dict | None = None,
         ok: tuple[int, ...] = (200, 201)) -> dict:
    r = client.request(method, BASE + path, json=body, headers=HEADERS, timeout=60)
    if r.status_code not in ok:
        raise SystemExit(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
    return r.json()


def simulated_verdicts(anchors: dict[str, str], wrong: int) -> dict[str, str]:
    labels = sorted(set(anchors.values()))
    verdicts = dict(anchors)
    for key in sorted(anchors)[:wrong]:
        verdicts[key] = next(label for label in labels if label != anchors[key])
    return verdicts


def main() -> int:
    with httpx.Client() as client:
        health = call(client, "GET", "/health")
        if health.get("env") != "development":
            print(f"refusing to seed a {health.get('env')} instance", file=sys.stderr)
            return 2

        for name, sut, runs, seed, why in SCENARIOS:
            call(client, "POST", "/api/v1/contracts", {"yaml": contract_yaml(name)}, ok=(201, 409))
            done = call(client, "GET", f"/api/v1/reports/{name}")["runs"]
            for t in range(done, runs):
                call(client, "POST", "/api/v1/runs",
                     {"contract": name, "sut": sut, "t": t, "seed": seed})
            report = call(client, "GET", f"/api/v1/reports/{name}")
            print(f"{name:16} {sut:17} runs={report['runs']:2} "
                  f"gate={report['latest_gate']['decision']:5}  {why}")

        anchor_file = REPO / "data" / "checks" / "judge_agreement_set.v1.json"
        items = json.loads(anchor_file.read_text(encoding="utf-8"))["items"]
        anchors = {i["id"]: i["gold_label"] for i in items if "gold_label" in i}
        existing = {j["judge"]: len(j["rounds"])
                    for j in call(client, "GET", "/api/v1/judges/calibration")["judges"]}
        # per judge: how many anchors it gets wrong in each successive round
        judges = {
            "sim-judge-steady": [0, 0, 1, 0, 0],
            "sim-judge-second": [1, 0, 0, 1, 0],
            "sim-judge-degraded": [0, 0, 1, 1, 4],
        }
        for judge, rounds in judges.items():
            for wrong in rounds[existing.get(judge, 0):]:
                call(client, "POST", "/api/v1/judges/calibration",
                     {"judge": judge, "verdicts": simulated_verdicts(anchors, wrong)})
        for j in call(client, "GET", "/api/v1/judges/calibration")["judges"]:
            state = f"quarantined ({j['reason']})" if j["quarantined"] else "active"
            print(f"{j['judge']:20} rounds={len(j['rounds'])} latest={j['latest_rate']:.2f} {state}")
    print("SEED OK. Simulators and simulated judges only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
