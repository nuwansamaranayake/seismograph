"use client";
import { GateBadge, SimulatorTag } from "@/components/Bits";
import { InvariantMatrix } from "@/components/InvariantMatrix";
import { ModeList } from "@/components/Modes";
import { Shell } from "@/components/Shell";
import { Data, Empty, Loading } from "@/components/States";
import { getRun } from "@/lib/api";
import { pct, perturbationLabel, when } from "@/lib/format";
import type { RunDetail } from "@/lib/types";
import { useApi, useQueryParam } from "@/lib/useApi";

function Detail({ run }: { run: RunDetail }) {
  const reasons = run.gate?.evidence.reasons ?? [];
  const skipped = run.gate?.evidence.skipped ?? [];
  return (
    <div className="stack">
      <div className="row">
        <GateBadge decision={run.gate?.decision ?? null} />
        <span className="badge">t = {run.t}</span>
        <span className="badge">seed {run.seed}</span>
        <span className="badge">embedder {run.embedder}</span>
        <span className="badge">{when(run.created_at)}</span>
      </div>
      <div className={`card ${run.gate?.decision === "block" ? "alarm" : "ok"}`}>
        <span className="label">Gate decision</span>
        {run.gate ? (
          <>
            <p>
              Worst flip rate <span className="num">{pct(run.gate.worst_flip_rate)}</span> against a tolerance of{" "}
              <span className="num">{pct(run.gate.threshold)}</span>.
            </p>
            {reasons.length ? (
              <ul>
                {reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            ) : (
              <p>Every declared tolerance held.</p>
            )}
          </>
        ) : (
          <p>No gate decision is stored for this run.</p>
        )}
        <p className="dim">
          System under test: <code>{run.sut}</code> <SimulatorTag />{" "}
          {run.simulator
            ? `${run.simulator.summary} ${run.simulator.planted_defect ? `Planted defect: ${run.simulator.planted_defect}.` : "No planted defect."}`
            : ""}
        </p>
      </div>
      <div className="card">
        <span className="label">Invariant matrix</span>
        <InvariantMatrix rows={run.matrix} />
        {skipped.map((cell) => (
          <p key={`${cell.probe}/${cell.perturbation}`} className="msg dim">
            Not measured: {cell.probe} / {cell.perturbation}: {cell.reason}
          </p>
        ))}
      </div>
      {run.modes.map((cell) => (
        <div className="card" key={`${cell.probe}/${cell.perturbation}`}>
          <div className="row spread">
            <span className="label">
              Outcome modes · {cell.probe} · {perturbationLabel(cell.perturbation)} · {cell.n} samples
            </span>
            {cell.modes.length > 1 ? (
              <span className={`badge ${cell.second_mode_detected ? "block" : ""}`.trim()}>
                second mode {pct(cell.second_mode_share)}
              </span>
            ) : (
              <span className="badge pass">one mode</span>
            )}
          </div>
          <ModeList modes={cell.modes} order={cell.modes.map((m) => m.key)} />
        </div>
      ))}
    </div>
  );
}

export default function RunPage() {
  const raw = useQueryParam("id");
  const id = raw && /^\d+$/.test(raw) ? Number(raw) : null;
  const { state, reload } = useApi(id !== null ? () => getRun(id) : null, id ?? "");
  return (
    <Shell active="contracts">
      <span className="label">Run</span>
      <h1>
        Run <em>{id ?? ""}</em>
      </h1>
      {raw === undefined ? (
        <Loading what="the address" />
      ) : id === null ? (
        <Empty title="No run named in the address">
          Open a run from a contract&apos;s run history on the <a href="/contracts/">contracts list</a>.
        </Empty>
      ) : (
        <Data state={state} reload={reload} what="the run">
          {(run) => (
            <>
              <p className="lede">
                Contract <a href={`/contract/?name=${encodeURIComponent(run.contract)}`}>{run.contract}</a>
              </p>
              <Detail run={run} />
            </>
          )}
        </Data>
      )}
    </Shell>
  );
}
