"use client";
import { Stat, Strip } from "@/components/Bits";
import { ContractTable } from "@/components/ContractTable";
import { Limits, OperatingCurve } from "@/components/Published";
import { Shell } from "@/components/Shell";
import { Data, Empty } from "@/components/States";
import { getOverview } from "@/lib/api";
import type { Overview } from "@/lib/types";
import { useApi } from "@/lib/useApi";

function Board({ overview }: { overview: Overview }) {
  if (overview.contracts === 0) {
    return (
      <Empty title="No contracts registered yet">
        Nothing has been measured on this instance, so there is nothing to show. <a href="/contracts/">Register a contract</a>{" "}
        or follow the <a href="/guide/">guide</a> to record a first trace in about five minutes.
      </Empty>
    );
  }
  return (
    <div className="stack">
      <div className="grid stats">
        <Stat label="Contracts" value={overview.contracts} note={`${overview.never_run} never run`} />
        <Stat label="Runs recorded" value={overview.runs} />
        <Stat label="Gate passing" value={overview.passing} tone={overview.passing ? "good" : undefined} />
        <Stat label="Gate blocking" value={overview.blocked} tone={overview.blocked ? "bad" : undefined} />
        <Stat label="Chart signals" value={overview.alarms} tone={overview.alarms ? "bad" : undefined} />
        <Stat
          label="Cells with a second mode, latest runs"
          value={overview.cells_with_second_mode}
          tone={overview.cells_with_second_mode ? "warn" : undefined}
        />
        <Stat
          label="Judges quarantined"
          value={`${overview.judges.quarantined} / ${overview.judges.total}`}
          tone={overview.judges.quarantined ? "warn" : undefined}
        />
      </div>
      <div className="card">
        <span className="label">Contracts</span>
        <ContractTable contracts={overview.latest} />
      </div>
    </div>
  );
}

export default function OverviewPage() {
  const { state, reload } = useApi(getOverview);
  const busiest =
    state.status === "ready"
      ? [...state.data.latest].sort((a, b) => b.alarms - a.alarms || b.trend.length - a.trend.length)[0]
      : undefined;
  const series = busiest?.trend ?? [];
  return (
    <Shell active="overview">
      <span className="label">Overview</span>
      <h1>
        How consistent is your AI system, <em>and did it just change?</em>
      </h1>
      <p className="lede">
        Seismograph runs the same question at an AI system many times and charts how much the answers move. A control
        chart turns that movement into a signal. Deterministic code makes every decision on this board.
      </p>
      <div className="card reveal" style={{ padding: "0.4rem 0.6rem", marginBottom: "1.2rem" }}>
        <Strip
          series={series}
          label={series.length ? `worst flip rate per run, ${busiest?.name}` : "no signal recorded yet"}
        />
        <span className="label">
          {series.length ? `trace · ${busiest?.name} · worst flip rate per run` : "trace · no signal recorded yet"}
        </span>
      </div>
      <Data state={state} reload={reload} what="the board">
        {(overview) => <Board overview={overview} />}
      </Data>
      <section className="stack" style={{ marginTop: "2.4rem" }}>
        <h2>
          What this instrument can see, <em>and what it misses</em>
        </h2>
        <Limits />
        <OperatingCurve />
      </section>
    </Shell>
  );
}
