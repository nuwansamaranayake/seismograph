from __future__ import annotations

import json
from pathlib import Path

_DEMO = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "demo.json"


def load_synthetic_fixture() -> list[dict]:
    """Load the tiny synthetic demo dataset. Fail loud if missing — never fabricate.

    The dataset exists so the demo runs with zero external keys in development. Outside
    development the demo endpoint is disabled entirely (see app.main), per Standard 3.
    """
    if not _DEMO.exists():
        raise NotImplementedError(
            f"Synthetic demo dataset not found at {_DEMO}. It must exist for the development "
            "demo; there is no silent fallback."
        )
    data = json.loads(_DEMO.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("data/synthetic/demo.json must be a JSON array of objects.")
    return data
