"""TEST FIXTURE — a stand-in Kalika target. Never reachable from a real run.

This file exists so g4's two exit-code criteria can be proven without calling
production Kalika: one instance answers correctly, the other answers with a
planted defect, and the CLI must tell them apart by exit code alone.

It is wired up ONLY by docker-compose.test.yml, which no deploy path reads, and
it refuses to answer for a case it was not given a golden record for. It is not
a fallback for a real target: nothing in app/ imports it and no env var in the
production path points at it.

    KALIKA_STUB_MODE=clean      answers from the case's golden reference
    KALIKA_STUB_MODE=tampered   plants the two defects g4 names: the wrong
                                lagna (in the chart and in the prose that
                                quotes it) and a gemstone prescription
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SIGNS = ["Mesha", "Vrishabha", "Mithuna", "Karka", "Simha", "Kanya",
         "Tula", "Vrischika", "Dhanu", "Makara", "Kumbha", "Meena"]

MODE = os.environ.get("KALIKA_STUB_MODE", "clean")
SUITE_DIR = Path(os.environ.get("SUITE_DIR", "suites/kalika"))
PORT = int(os.environ.get("PORT", "8900"))


def _cases() -> dict[str, dict]:
    return {
        c["id"]: c
        for c in (json.loads(p.read_text(encoding="utf-8"))
                  for p in sorted((SUITE_DIR / "cases").glob("*.json")))
    }


def _clean_prose(chart: dict) -> str:
    return (
        f"Your lagna is {chart['lagna']}, and the Moon sits in "
        f"{chart['moon_nakshatra']} pada {chart['moon_pada']}. You are running the "
        f"{chart['mahadasha_lord']} mahadasha, with about "
        f"{chart['mahadasha_years_remaining']} years left in it. This period rewards "
        "steady discipline over sudden moves. The chart shows a tendency, not a "
        "verdict: you can choose how you meet it, and consistent effort in the work "
        "you already do is what turns the period."
    )


def _tampered_prose(chart: dict) -> str:
    return (
        f"Your lagna is {chart['lagna']}, and the Moon sits in "
        f"{chart['moon_nakshatra']} pada {chart['moon_pada']}. You are running the "
        f"{chart['mahadasha_lord']} mahadasha. To correct this period you should wear "
        "a blue sapphire gemstone set in silver on the middle finger, from a Saturday "
        "morning onward. Until you do, effort alone will not move the result."
    )


def answer(case: dict) -> dict:
    reference = case["reference"]
    chart = {
        "lagna": reference["lagna"],
        "moon_nakshatra": reference["moon_nakshatra"],
        "moon_pada": reference["moon_pada"],
        "mahadasha_lord": reference["mahadasha_lord"],
        "mahadasha_years_remaining": reference["mahadasha_years_remaining"],
    }
    if MODE == "tampered":
        # One sign off — the defect a reader would never catch and a check must.
        chart["lagna"] = SIGNS[(SIGNS.index(reference["lagna"]) + 1) % len(SIGNS)]
        prose = _tampered_prose(chart)
    else:
        prose = _clean_prose(chart)
    return {"case_id": case["id"], "mode": MODE, "chart": chart, "prose": prose}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's naming
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "body is not JSON"})
        case = _cases().get(body.get("case_id", ""))
        if case is None:
            return self._send(404, {"error": f"no golden case {body.get('case_id')!r}"})
        return self._send(200, answer(case))

    def do_GET(self) -> None:  # noqa: N802
        self._send(200, {"fixture": "kalika_stub", "mode": MODE, "cases": sorted(_cases())})

    def _send(self, status: int, payload: dict) -> None:
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args) -> None:
        """Quiet: the gate reads the CLI's output, not this server's access log."""


if __name__ == "__main__":
    print(f"kalika_stub mode={MODE} port={PORT} cases={sorted(_cases())}", flush=True)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
