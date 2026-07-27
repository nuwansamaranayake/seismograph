"""Key-gated eval: the metamorphic paraphrase back-check, at a volume that means something.

The Phase 1 report cited 4 accepted out of 4 variants. Four is not a sample; it cannot
distinguish a working back-check from one that accepts everything. This harness generates at
least MIN_VARIANTS paraphrases across deliberately varied statement types and reports the
accepted rate with a 95% Wilson interval, plus the rejection reasons.

It also plants NEGATIVE controls: text that is not a paraphrase at all. A back-check that
accepts those is not a gate, so its rejection is asserted, not merely reported.

Never a required keyless check, and never a silent skip: without a key it exits 2 loudly.
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from groundwork import BaseConfig, LLMGateway  # noqa: E402
from app.engine.embedding import HashingEmbedder, OpenRouterEmbedder  # noqa: E402
from app.engine.golden import wilson  # noqa: E402
from app.engine.metamorphic import (  # noqa: E402
    MAX_SIMILARITY, MIN_SIMILARITY, generate_paraphrases,
)

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "eval_report_llm.md"

MIN_VARIANTS = 50
PER_SEED = 6

# Varied statement types: a back-check tuned on one register can look perfect and still fail
# on numbers, negation, policy language or multi-clause conditionals.
SEEDS: list[tuple[str, str]] = [
    ("question",
     "Customer bought a blender 12 days ago, unopened. Are they refund eligible?"),
    ("numeric",
     "The order totalled 249.99 dollars across 3 line items and shipped on 14 March."),
    ("negation",
     "The customer did not request a replacement and does not want store credit."),
    ("policy",
     "Refunds are issued within 30 days of delivery when the item is unopened."),
    ("conditional",
     "If the package was marked delivered but never arrived, open a carrier claim first."),
    ("instruction",
     "Verify the shipping address, then cancel the duplicate order before refunding."),
    ("multi_clause",
     "She escalated the ticket on Tuesday, the depot confirmed the loss on Thursday, "
     "and the refund cleared the following Monday."),
    ("terse",
     "Item unopened. Twelve days. Refund?"),
    ("formal",
     "Please advise whether the aforementioned transaction qualifies for reimbursement "
     "under the current returns policy."),
]

# Not paraphrases. The back-check must reject every one of these.
NEGATIVE_CONTROLS: list[tuple[str, str]] = [
    ("off_topic", "The weather in Lisbon is pleasant throughout the spring months."),
    ("contradiction", "The customer opened the box and used the blender for three weeks."),
    ("number_changed",
     "Customer bought a blender 120 days ago, unopened. Are they refund eligible?"),
]


class _FixedGateway:
    """Feeds pre-authored text through the same back-check path as the model's output."""

    def __init__(self, texts: list[str]):
        self._texts = texts

    def complete(self, *, model, messages, json_schema=None, temperature=0.0):
        return {"paraphrases": self._texts}


def main() -> None:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    model = os.environ.get("LLM_MODEL_EXTRACTION", "")
    if not key or not model:
        print("eval_llm: NOT RUN — OPENROUTER_API_KEY / LLM_MODEL_EXTRACTION missing. This "
              "section is key-gated by design; scripts/eval.py is the required gate.",
              file=sys.stderr)
        sys.exit(2)

    cfg = BaseConfig(openrouter_api_key=key)
    gateway = LLMGateway(cfg)
    embed_model = os.environ.get("EMBEDDING_MODEL", "")
    embedder = (OpenRouterEmbedder(api_key=key, model=embed_model)
                if embed_model else HashingEmbedder())

    rows, reasons, by_type = [], Counter(), {}
    accepted = total = 0
    for kind, seed_text in SEEDS:
        variants = generate_paraphrases(gateway, model, seed_text, PER_SEED, embedder)
        a = sum(1 for v in variants if v.accepted)
        accepted += a
        total += len(variants)
        by_type[kind] = (a, len(variants))
        for v in variants:
            reasons[v.reason] += 1
        rows.append(f"| {kind} | {a}/{len(variants)} | "
                    f"{min((v.back_check_score for v in variants), default=0):.3f} | "
                    f"{max((v.back_check_score for v in variants), default=0):.3f} |")

    if total < MIN_VARIANTS:
        print(f"EVAL_LLM FAILED: only {total} variants generated, need >= {MIN_VARIANTS} "
              "for the accepted rate to carry a usable interval", file=sys.stderr)
        sys.exit(1)

    # Negative controls through the identical back-check.
    neg_texts = [t for _, t in NEGATIVE_CONTROLS]
    neg = generate_paraphrases(_FixedGateway(neg_texts), model, SEEDS[0][1],
                               len(neg_texts), embedder)
    leaked = [v for v in neg if v.accepted]

    p, lo, hi = wilson(accepted, total)
    lines = [
        "# Seismograph metamorphic back-check (key-gated)",
        "",
        f"model: `{model}`   embedder: `{embedder.name}`",
        f"acceptance band: {MIN_SIMILARITY} <= cosine <= {MAX_SIMILARITY}",
        "",
        f"**Accepted {accepted}/{total} variants = {p:.2f} (95% CI {lo:.2f}-{hi:.2f})** "
        f"across {len(SEEDS)} statement types.",
        "",
        "| statement type | accepted | min score | max score |",
        "|---|---|---|---|",
        *rows,
        "",
        "## Rejection reasons",
        "",
        *[f"- `{r}`: {n}" for r, n in sorted(reasons.items())],
        "",
        "## Negative controls (must all be rejected)",
        "",
        *[f"- `{k}`: {'ACCEPTED (LEAK)' if v.accepted else 'rejected'} "
          f"(score {v.back_check_score:.3f}, {v.reason})"
          for (k, _), v in zip(NEGATIVE_CONTROLS, neg)],
    ]
    text = "\n".join(lines) + "\n"
    REPORT.write_text(text, encoding="utf-8", newline="\n")
    print(text)

    if leaked:
        print(f"EVAL_LLM FAILED: back-check accepted {len(leaked)} negative control(s); "
              "it is not gating anything", file=sys.stderr)
        sys.exit(1)
    print("EVAL_LLM OK")


if __name__ == "__main__":
    main()
