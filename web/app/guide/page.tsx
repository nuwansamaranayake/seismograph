import type { ReactNode } from "react";
import { Limits } from "@/components/Published";
import { Shell } from "@/components/Shell";

const INVARIANTS = [
  {
    name: "Repeat run",
    key: "repeat_run",
    change: "Nothing. The same input, asked again.",
    catches: "Run to run noise, drift over time, and malformed output.",
  },
  {
    name: "Irrelevance",
    key: "irrelevant_context",
    change: "One unrelated sentence is added before or after the input.",
    catches: "A system swayed by text that has no bearing on the question.",
  },
  {
    name: "Order",
    key: "reordering",
    change: "The sentences of the input are reordered.",
    catches: "A system that reads only the start, or stops at the question mark.",
  },
  {
    name: "Format",
    key: "format",
    change: "Same words, different case, spacing and line breaks.",
    catches: "A brittle parser in front of the model.",
  },
  {
    name: "Monotonicity",
    key: "monotonic",
    change: "A ladder of inputs along one quantity, such as days since purchase.",
    catches: "An answer that moves the wrong way as the quantity grows.",
  },
  {
    name: "Paraphrase",
    key: "paraphrase",
    change: "A model proposes rewordings. Code accepts only the ones that keep every number.",
    catches: "A decision that depends on phrasing.",
  },
] as const;

function Step({ n, title, children }: { n: number; title: ReactNode; children: ReactNode }) {
  return (
    <section className="step" id={`step-${n}`}>
      <div className="n" aria-hidden="true">
        {n}
      </div>
      <div>
        <h2>{title}</h2>
        {children}
      </div>
    </section>
  );
}

function Shot({ src, alt, caption }: { src: string; alt: string; caption: string }) {
  return (
    <figure className="figure">
      <img src={src} alt={alt} loading="lazy" />
      <figcaption>{caption}</figcaption>
    </figure>
  );
}

/** How to read a control chart, drawn rather than described. Illustrative shape, no data. */
function ChartAnatomy() {
  const points = [34, 30, 36, 31, 33, 29, 35, 32, 31, 34, 30, 33, 62, 70, 66];
  const x = (i: number) => 60 + i * 44;
  const y = (v: number) => 190 - v * 2;
  return (
    <figure className="figure">
      <svg className="chart" viewBox="0 0 760 230" role="img" aria-label="Anatomy of a control chart">
        <rect className="baseline-band" x="60" y="20" width={x(7) - 60} height="170" />
        <line className="limit" x1="60" x2="720" y1={y(48)} y2={y(48)} />
        <line className="center" x1="60" x2="720" y1={y(32.5)} y2={y(32.5)} />
        <polyline className="series" points={points.map((v, i) => `${x(i)},${y(v)}`).join(" ")} />
        {points.map((v, i) => (
          <circle key={i} className={`dot ${i >= 12 ? "alarm" : i >= 8 ? "judged" : ""}`.trim()} cx={x(i)} cy={y(v)} r="3.4" />
        ))}
        <text x="66" y="34">1. baseline: the first 8 runs set the limits. They are never judged.</text>
        <text x="724" y={y(48) - 6} textAnchor="end">2. control limit: 3 sigma above the baseline mean. Frozen.</text>
        <text x="724" y={y(32.5) + 14} textAnchor="end">baseline mean</text>
        <text x={x(12) - 8} y={y(70) - 12} textAnchor="end">3. signal: a point beyond the limit. The process changed.</text>
        <text x="60" y="214">run 0</text>
        <text x="720" y="214" textAnchor="end">latest run</text>
      </svg>
      <div className="cap">Illustration of the three things to read on a control chart. Shape only, not measured data.</div>
    </figure>
  );
}

export default function GuidePage() {
  return (
    <Shell active="guide">
      <span className="label">Guide · evaluating an AI system with Seismograph</span>
      <h1>
        Evaluate the process, <em>not the sample</em>
      </h1>
      <p className="lede">
        One good answer tells you little about a system that answers differently each time. This guide walks the whole
        loop in seven steps: declare what must not change, run it many times, read the chart, read the modes, and let a
        deterministic gate decide the release.
      </p>

      <div className="flow" aria-label="The loop">
        <div>
          <b>Declare</b>
          <span className="dim small">A contract: fields that must hold still, and the tolerance.</span>
        </div>
        <div>
          <b>Sample</b>
          <span className="dim small">The same probe, many times, under each change to the input.</span>
        </div>
        <div>
          <b>Reduce</b>
          <span className="dim small">Flip rate, malformed rate, set overlap, outcome modes.</span>
        </div>
        <div>
          <b>Chart</b>
          <span className="dim small">Limits from your own baseline. A point outside is a signal.</span>
        </div>
        <div>
          <b>Gate</b>
          <span className="dim small">Code decides pass or block. The evidence is attached.</span>
        </div>
      </div>

      <Step n={1} title="Start the instrument">
        <p>You need Docker. No API key is needed for anything in this guide.</p>
        <pre>{`git clone https://github.com/nuwansamaranayake/Seismograph
cd Seismograph
cp .env.example .env
docker compose up -d --build
# open http://localhost:8000`}</pre>
        <p className="dim">
          In development the API runs without a token. Anywhere else it refuses to start without one, and this dashboard
          asks for it before showing a single number.
        </p>
        <Shot
          src="/guide/overview.png"
          alt="The overview board listing contracts with their gate state, trend, and chart signals"
          caption="The overview board. Every figure on it is read from the API. An empty instance says so."
        />
      </Step>

      <Step n={2} title={<>Declare what must <em>not</em> change</>}>
        <p>
          A contract is a YAML file that lives beside your prompt. It names fields of the answer, the changes to the
          input each field must survive, and the tolerance the gate enforces. Open <a href="/contracts/">Contracts</a>,
          keep or edit the example, and press Register and compile.
        </p>
        <pre>{`contract: refund-full-invariants
subject: support-agent
invariants:
  - field: eligibility_decision          # this field of the answer
    under: [repeat_run, irrelevant_context, reordering, format]
    relation: equal                      # must be the same under each change
  - field: cited_policy_ids
    under: [repeat_run]
    relation: jaccard_at_least           # set overlap between runs
    threshold: 0.85
  - field: eligibility_decision
    under: [monotonic]
    relation: monotonic                  # may only move in this direction
    order: [eligible, ineligible]
run_policy: {samples: 20, configs: 1, confidence: 0.95}
gate: {max_decision_flip_rate: 0.10, max_malformed_rate: 0.05}
probes:
  - id: refund-basic
    input: "Customer bought a blender 12 days ago, unopened. Are they refund eligible?"`}</pre>
        <div className="grid two">
          {INVARIANTS.map((invariant) => (
            <div className="card" key={invariant.key}>
              <span className="label">{invariant.key}</span>
              <h3>{invariant.name}</h3>
              <p>{invariant.change}</p>
              <p className="dim">Catches: {invariant.catches}</p>
            </div>
          ))}
        </div>
        <p className="dim">
          A perturbed answer is compared with the answer to the unperturbed input. If every variant is wrong in the same
          way, the variants agree with each other perfectly, and that must still count as a failure.
        </p>
      </Step>

      <Step n={3} title="Point it at a system">
        <p>
          Your system is any Python object with one method. It receives the probe text and returns JSON text carrying
          the fields your contract names.
        </p>
        <pre>{`# my_app/eval.py
import json

class RefundAgent:
    def run(self, probe_input: str, t: int, rng) -> str:
        answer = call_my_agent(probe_input)          # your LLM application
        return json.dumps({
            "eligibility_decision": answer.decision,
            "cited_policy_ids": answer.policies,
            "response_wording": answer.text,
        })

sut = RefundAgent()`}</pre>
        <p>
          To learn the instrument first, use the built-in simulators. Each one is a small program with one defect
          planted on purpose, so you can watch the instrument catch a defect you know is there. They are labelled{" "}
          <span className="badge sim">simulator</span> everywhere they appear, and nothing they produce is a measurement
          of a real system.
        </p>
        <p>Every screenshot in this guide was recorded by one command against a fresh instance:</p>
        <pre>{`python scripts/seed_demo.py     # four contracts, four simulators, same seeds every time`}</pre>
      </Step>

      <Step n={4} title="Run it, then read the chart">
        <p>
          Open the contract and launch runs. Each run is one point. The first eight set the baseline, and from the ninth
          on each point is judged against limits computed from that baseline. Choose the <code>jump</code> simulator and
          launch 12 runs twice: its flip rate jumps at run 12.
        </p>
        <ChartAnatomy />
        <Shot
          src="/guide/charts.png"
          alt="Control charts for flip rate and malformed rate with a signal after the planted jump"
          caption="A recorded run of the jump simulator. The chart is quiet through the baseline and signals at the planted onset."
        />
        <p className="dim">
          The gold line is not a target you chose. It is where your own baseline says ordinary noise ends. The red
          dotted line is the tolerance you declared in the contract. They answer different questions: did the process
          change, and is it still good enough to ship.
        </p>
      </Step>

      <Step n={5} title="Find which invariant broke">
        <p>
          The invariant matrix shows the latest run cell by cell: probes down, changes to the input across. Zero means
          the answer held. A red cell names the exact condition under which your system stops being consistent.
        </p>
        <Shot
          src="/guide/matrix.png"
          alt="Invariant matrix with one violated cell under the format perturbation"
          caption="The format-sensitive simulator: consistent on repeat runs, broken by upper case and doubled spaces."
        />
      </Step>

      <Step n={6} title="Look for the second mode">
        <p>
          An average hides shape. A system can keep its decision field perfectly stable while one answer in ten reaches
          that decision by a different route. The mode view groups answers by their signature over the invariant fields
          and pools a window of runs, so a small mode that keeps coming back is reported with a confidence bound.
        </p>
        <Shot
          src="/guide/modes.png"
          alt="Mode topology showing a persistent second band and the pooled share with its Wilson bound"
          caption="The bimodal simulator. The flip chart stays flat at zero. The mode view shows the second behaviour."
        />
      </Step>

      <Step n={7} title="Gate the release">
        <p>
          The same engine runs as one command. It exits 0 on pass, 1 on block, and 2 when the gate could not be
          evaluated, and writes a summary a reviewer can read on the pull request.
        </p>
        <pre>{`seismo gate --contract contracts/refund.yaml --sut my_app.eval:sut --points 12`}</pre>
        <pre>{`# .github/workflows/seismograph.yml
on: [pull_request]
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: nuwansamaranayake/Seismograph@main
        with:
          contract: contracts/refund.yaml
          sut: my_app.eval:sut`}</pre>
      </Step>

      <section className="stack" style={{ marginTop: "1.5rem" }}>
        <h2>
          If a model scores your answers, <em>measure the scorer</em>
        </h2>
        <p>
          A judge model is an instrument too. The <a href="/judges/">Judge panel</a> scores each judge against labelled
          anchor items, with an interval and a chance-corrected kappa. A judge that falls under the agreement floor, or
          drifts from its own baseline, is quarantined. Its vote is then excluded by name, and a panel left without a
          quorum returns no verdict.
        </p>
        <Shot
          src="/guide/judges.png"
          alt="Judge panel with two active judges and one quarantined below the agreement floor"
          caption="Three simulated judges. One agreed with 60% of the anchors on its latest round and is quarantined."
        />
        <h2>
          Where you have labels, <em>score against them</em>
        </h2>
        <p>
          A contract can carry a golden set: items a person labelled. <a href="/golden/">Golden sets</a> shows the
          committed reports of those runs against a live model, with recall, false positives, a reliability diagram and
          agreement between two model versions. Each report states the one model build and the one set it describes.
        </p>
        <Shot
          src="/guide/golden.png"
          alt="Golden-set report with recall, cost, a scope note and a reliability diagram"
          caption="A committed report of a real run: 130 labelled excerpts, five runs each, against one model build."
        />
      </section>

      <section className="stack" style={{ marginTop: "1.5rem" }}>
        <h2>
          What it cannot see
        </h2>
        <Limits />
        <div className="grid two">
          <div className="card ok">
            <span className="label">Shipped</span>
            <ul>
              <li>Contracts, the sampler, flip, malformed and overlap metrics</li>
              <li>Six invariants, including monotonicity</li>
              <li>X chart and p chart with frozen limits</li>
              <li>Outcome modes with a pooled confidence bound</li>
              <li>Judge calibration, quarantine and panel verdict</li>
              <li>The CI gate and this dashboard</li>
            </ul>
          </div>
          <div className="card">
            <span className="label">Planned, not built</span>
            <ul>
              <li>Fault attribution under controlled replay</li>
              <li>Scheduled production monitoring with re-baselining</li>
              <li>Benchmarking across providers</li>
              <li>An incident narrator grounded in verified statistics</li>
            </ul>
          </div>
        </div>
      </section>
    </Shell>
  );
}
