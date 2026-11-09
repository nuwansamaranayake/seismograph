import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GateBadge, SimulatorTag, Sparkline, Stat, Strip } from "@/components/Bits";
import { ContractTable } from "@/components/ContractTable";
import { ControlChart } from "@/components/ControlChart";
import { InvariantMatrix } from "@/components/InvariantMatrix";
import { ModeList, ModeRiver, modeColor } from "@/components/Modes";
import { Reliability } from "@/components/Reliability";
import { NAV, Shell } from "@/components/Shell";
import { Connect, Data, Empty, ErrorPanel, Loading } from "@/components/States";
import { ApiError, getToken } from "@/lib/api";
import {
  BINS,
  blockedSummary,
  chartPoint,
  coldChart,
  contractSummary,
  matrixRow,
  mode,
  modeCell,
  secondModeCell,
  warmChart,
} from "./fixtures";

describe("States", () => {
  it("Loading announces what it is reading", () => {
    render(<Loading what="the board" />);
    expect(screen.getByRole("status")).toHaveTextContent("Reading the board");
  });

  it("Empty says nothing is recorded and shows its explanation", () => {
    render(<Empty title="No contracts">Register one.</Empty>);
    expect(screen.getByText("Nothing recorded")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No contracts" })).toBeInTheDocument();
    expect(screen.getByText("Register one.")).toBeInTheDocument();
  });

  it("Connect keeps Connect disabled until a token is typed, then stores the trimmed token and calls back", async () => {
    const onConnected = vi.fn();
    render(<Connect onConnected={onConnected} />);
    const button = screen.getByRole("button", { name: "Connect" });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText("API token"), "  tok-1  ");
    expect(button).toBeEnabled();
    await userEvent.click(button);
    expect(getToken()).toBe("tok-1");
    expect(onConnected).toHaveBeenCalledOnce();
  });

  it("ErrorPanel renders the token form for an unauthorized error", () => {
    render(<ErrorPanel error={new ApiError("unauthorized", "no", 401)} onRetry={() => {}} />);
    expect(screen.getByLabelText("API token")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each([
    ["not_found", "Not found"],
    ["invalid", "The API rejected the request"],
    ["unavailable", "Not available on this instance"],
    ["network", "The API could not be reached"],
    ["server", "The API returned an error"],
  ] as const)("ErrorPanel shows the %s message in an alert and retries on request", async (kind, headline) => {
    const onRetry = vi.fn();
    render(<ErrorPanel error={new ApiError(kind, "the reason", 500)} onRetry={onRetry} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(headline);
    expect(alert).toHaveTextContent("the reason");
    expect(alert).toHaveTextContent("does not fill in numbers it did not receive");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("Data shows the wait, then the error, then only the data's children", () => {
    const child = vi.fn((n: number) => <p>value {n}</p>);
    const { rerender } = render(<Data state={{ status: "loading" }} reload={() => {}} what="x">{child}</Data>);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(child).not.toHaveBeenCalled();
    rerender(
      <Data state={{ status: "error", error: new ApiError("server", "bad") }} reload={() => {}} what="x">
        {child}
      </Data>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("bad");
    expect(child).not.toHaveBeenCalled();
    rerender(<Data state={{ status: "ready", data: 4 }} reload={() => {}} what="x">{child}</Data>);
    expect(screen.getByText("value 4")).toBeInTheDocument();
  });
});

describe("Shell", () => {
  it("marks only the active section with aria-current and links every section", () => {
    render(
      <Shell active="judges">
        <p>body</p>
      </Shell>,
    );
    const nav = screen.getByRole("navigation", { name: "Sections" });
    const links = within(nav).getAllByRole("link");
    expect(links).toHaveLength(NAV.length);
    expect(within(nav).getByRole("link", { name: "Judge panel" })).toHaveAttribute("aria-current", "page");
    expect(links.filter((l) => l.hasAttribute("aria-current"))).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Seismograph home" })).toHaveAttribute("href", "/");
    expect(screen.getByText("body")).toBeInTheDocument();
  });
});

describe("Bits", () => {
  it("GateBadge shows the decision or says no runs", () => {
    const { rerender } = render(<GateBadge decision="block" />);
    expect(screen.getByText("block")).toHaveClass("block");
    rerender(<GateBadge decision="pass" />);
    expect(screen.getByText("pass")).toHaveClass("pass");
    rerender(<GateBadge decision={null} />);
    expect(screen.getByText("no runs")).toBeInTheDocument();
  });

  it("SimulatorTag says this is not a real system", () => {
    render(<SimulatorTag />);
    expect(screen.getByText("simulator")).toHaveAttribute("title", expect.stringContaining("Not a real system"));
  });

  it("Stat shows label, value, tone and an optional note", () => {
    const { rerender } = render(<Stat label="Runs" value={3} tone="bad" note="all time" />);
    expect(screen.getByText("Runs").closest(".stat")).toHaveClass("bad");
    expect(screen.getByText("all time")).toBeInTheDocument();
    rerender(<Stat label="Runs" value={3} />);
    expect(screen.queryByText("all time")).toBeNull();
    expect(screen.getByText("Runs").closest(".stat")?.className.trim()).toBe("card stat");
  });

  it("Strip draws the series as a labelled trace, and a flat line when empty", () => {
    const { rerender, container } = render(<Strip series={[0.1, 0.3]} label="trace of two" />);
    expect(screen.getByRole("img", { name: "trace of two" })).toBeInTheDocument();
    const swung = container.querySelector("polyline")?.getAttribute("points");
    rerender(<Strip series={[]} label="empty" />);
    const flat = container.querySelector("polyline")?.getAttribute("points");
    expect(flat?.split(" ")).toHaveLength(2);
    expect(swung?.split(" ").length).toBeGreaterThan(2);
  });

  it("Sparkline needs two points: otherwise it says 1 run or no runs", () => {
    const { rerender } = render(<Sparkline series={[]} blocked={false} />);
    expect(screen.getByText("no runs")).toBeInTheDocument();
    rerender(<Sparkline series={[0.1]} blocked={false} />);
    expect(screen.getByText("1 run")).toBeInTheDocument();
    rerender(<Sparkline series={[0.1, 0.2, 0.3]} blocked />);
    const svg = screen.getByRole("img", { name: "worst flip rate over the last 3 runs" });
    expect(svg).toHaveClass("block");
    rerender(<Sparkline series={[0.1, 0.2]} blocked={false} />);
    expect(screen.getByRole("img")).not.toHaveClass("block");
  });
});

describe("ControlChart", () => {
  const lines = (c: HTMLElement) => [...c.querySelectorAll("[data-line]")].map((l) => l.getAttribute("data-line"));

  it("with no values it says there are no runs yet and draws no chart", () => {
    render(<ControlChart title="Flip" values={[]} chart={coldChart()} />);
    expect(screen.getByText(/No runs yet/)).toBeInTheDocument();
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("a cold chart draws no limit lines and says how many more runs are needed", () => {
    const { container } = render(<ControlChart title="Flip" values={[0.02, 0.03, 0.04]} chart={coldChart({ runs_until_warm: 5 })} />);
    expect(container.querySelector('[data-line="ucl"]')).toBeNull();
    expect(container.querySelector('[data-line="center"]')).toBeNull();
    expect(screen.getByText("warming · 5 more runs")).toBeInTheDocument();
    expect(screen.queryByText("control limit, 3 sigma from the baseline")).toBeNull();
  });

  it("uses the singular for one more run", () => {
    render(<ControlChart title="Flip" values={[0.02]} chart={coldChart({ runs_until_warm: 1 })} />);
    expect(screen.getByText("warming · 1 more run")).toBeInTheDocument();
  });

  it("a warm chart draws the limit and centre lines and says in control", () => {
    const { container } = render(<ControlChart title="Flip" values={[0.04, 0.05, 0.03]} chart={warmChart()} />);
    expect(lines(container)).toEqual(expect.arrayContaining(["ucl", "center"]));
    expect(lines(container)).not.toContain("lcl");
    expect(screen.getByText("in control")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Flip control chart" })).toBeInTheDocument();
    expect(container.querySelector(".msg.err")).toBeNull();
  });

  it("draws a lower limit only when it is above zero", () => {
    const points = [chartPoint(0, { lcl: 0.01 })];
    const { container } = render(<ControlChart title="Flip" values={[0.04]} chart={warmChart({ points })} />);
    expect(lines(container)).toContain("lcl");
  });

  it("draws the tolerance line and legend only when a tolerance is passed", () => {
    const { container, rerender } = render(<ControlChart title="Flip" values={[0.04, 0.05]} chart={warmChart()} />);
    expect(container.querySelector('[data-line="tolerance"]')).toBeNull();
    expect(screen.queryByText(/declared tolerance/)).toBeNull();
    rerender(<ControlChart title="Flip" values={[0.04, 0.05]} chart={warmChart()} tolerance={0.1} />);
    expect(container.querySelector('[data-line="tolerance"]')).not.toBeNull();
    expect(screen.getByText(/declared tolerance 10\.0%/)).toBeInTheDocument();
    rerender(<ControlChart title="Flip" values={[0.04]} chart={warmChart()} tolerance={0.1} toleranceLabel="gate tolerance" />);
    expect(screen.getByText(/gate tolerance 10\.0%/)).toBeInTheDocument();
  });

  it("an alarm point gets a ring and the signal text names the run index", () => {
    const points = [chartPoint(0), chartPoint(1), chartPoint(2, { alarm: true, rule: "we1" })];
    const { container } = render(<ControlChart title="Flip" values={[0.04, 0.04, 0.4]} chart={warmChart({ points })} />);
    expect(container.querySelectorAll("circle.ring")).toHaveLength(1);
    expect(container.querySelectorAll("circle.dot.alarm")).toHaveLength(1);
    expect(screen.getByText("1 signal")).toBeInTheDocument();
    const message = container.querySelector(".msg.err");
    expect(message).toHaveTextContent("Signal at run 2.");
    expect(message).toHaveTextContent("A point beyond the control limit is a change in the process");
    expect(container.querySelector("title")?.textContent).toContain("run 0");
    expect(container).toHaveTextContent("signal we1");
  });

  it("several signals are counted in the plural and the run8 rule is explained", () => {
    const points = [chartPoint(0), chartPoint(1, { alarm: true, rule: "we1" }), chartPoint(2, { alarm: true, rule: "run8" })];
    const { container } = render(<ControlChart title="Flip" values={[0.04, 0.4, 0.05]} chart={warmChart({ points })} />);
    expect(screen.getByText("2 signals")).toBeInTheDocument();
    expect(container.querySelector(".msg.err")).toHaveTextContent("Signal at run 1, 2.");
    expect(container.querySelector(".msg.err")).toHaveTextContent("run8 is eight points in a row");
  });

  it("a chart with no judged points still draws its values and no limits", () => {
    const { container } = render(<ControlChart title="Flip" values={[0.04, 0.05]} chart={warmChart({ points: [] })} />);
    expect(lines(container)).toEqual([]);
    expect(container.querySelectorAll("circle.dot")).toHaveLength(2);
  });

  it("uses a finer percentage scale on a small axis", () => {
    const { container } = render(<ControlChart title="Flip" values={[0.001]} chart={coldChart()} />);
    expect(container.textContent).toMatch(/\d\.\d%/);
  });
});

describe("modes", () => {
  it("modeColor gives malformed the red, unknown keys the dim colour, and ranks the rest", () => {
    expect(modeColor("malformed", ["a"])).toBe("var(--red)");
    expect(modeColor("a", ["a", "b"])).toBe("var(--trace)");
    expect(modeColor("b", ["a", "b"])).toBe("var(--gold)");
    expect(modeColor("seventh", ["1", "2", "3", "4", "5", "6", "seventh"])).toBe("var(--trace)");
    expect(modeColor("ghost", ["a"])).toBe("var(--text-dim)");
  });

  it("ModeList names the usual answer, later modes by rank and malformed output", () => {
    render(
      <ModeList
        modes={[mode("eligible", 0.6), mode("denied", 0.3), mode("malformed", 0.1, { signature: {} })]}
        order={["eligible", "denied", "malformed"]}
      />,
    );
    expect(screen.getByText("Usual answer")).toBeInTheDocument();
    expect(screen.getByText("Mode 2")).toBeInTheDocument();
    expect(screen.getByText("Malformed output")).toBeInTheDocument();
    expect(screen.getByText("malformed output")).toBeInTheDocument();
    expect(screen.getByText("60.0%")).toBeInTheDocument();
  });

  it("ModeRiver for one mode says every answer has the same signature", () => {
    const { container } = render(<ModeRiver cell={modeCell("refund-basic", "repeat_run")} noiseFloor={0.1} />);
    expect(screen.getByText("one mode")).toBeInTheDocument();
    expect(screen.getByText(/every answer has the same signature/)).toBeInTheDocument();
    expect(container.querySelectorAll("rect[data-mode]")).toHaveLength(2);
  });

  it("ModeRiver for a detected second mode says it clears the noise floor", () => {
    const { container } = render(<ModeRiver cell={secondModeCell("refund-basic", "paraphrase")} noiseFloor={0.1} />);
    expect(screen.getByText("second mode detected")).toHaveClass("block");
    expect(container.querySelectorAll('rect[data-mode="denied"]')).toHaveLength(2);
    expect(container.querySelector(".msg.err")).toHaveTextContent("clears the 10% noise floor");
    expect(screen.getByText(/Mode topology · refund-basic · Paraphrase/)).toBeInTheDocument();
  });

  it("ModeRiver separates stray answers from a second behaviour", () => {
    const cell = modeCell("p", "repeat_run", {
      pooled: {
        n: 60,
        modes: [mode("eligible", 0.97), mode("denied", 0.03)],
        second_mode_share: 0.03,
        second_mode_low: 0.01,
        second_mode_detected: false,
      },
    });
    render(<ModeRiver cell={cell} noiseFloor={0.1} />);
    expect(screen.getByText("stray answers only")).toBeInTheDocument();
    expect(screen.getByText(/does not clear the 10% noise floor/)).toBeInTheDocument();
  });

  it("ModeRiver leaves out zero-share bands", () => {
    const cell = modeCell("p", "repeat_run", {
      pooled: { n: 20, modes: [mode("a", 0.5), mode("b", 0.5)], second_mode_share: 0.5, second_mode_low: 0.3, second_mode_detected: true },
      by_run: [{ run_id: 1, t: 0, n: 20, shares: { a: 1 } }],
    });
    const { container } = render(<ModeRiver cell={cell} noiseFloor={0.1} />);
    expect(container.querySelectorAll("rect[data-mode]")).toHaveLength(1);
  });
});

describe("InvariantMatrix", () => {
  it("says nothing was measured when there are no rows", () => {
    render(<InvariantMatrix rows={[]} />);
    expect(screen.getByText("No cells measured yet.")).toBeInTheDocument();
  });

  it("shows held and violated cells, malformed share, and marks unmeasured cells not run", () => {
    render(
      <InvariantMatrix
        rows={[
          matrixRow("refund-basic", "repeat_run", { flip_rate: 0.3, violated: true, malformed_rate: 0.05, jaccard_mean: { ids: 0.5 } }),
          matrixRow("refund-basic", "format", { flip_rate: 0 }),
          matrixRow("refund-late", "repeat_run"),
        ]}
      />,
    );
    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Probe", "Repeat run", "Format"]);
    const violated = screen.getByText(/30\.0%/).closest("td");
    expect(violated).toHaveClass("violated");
    expect(violated).toHaveTextContent("5.0% malformed");
    expect(violated).toHaveAttribute("title", expect.stringContaining("jaccard ids 0.500"));
    expect(screen.getByText("0.0%").closest("td")).toHaveClass("held");
    expect(screen.getByText("not run")).toHaveAttribute("title", "not measured in this run");
    expect(screen.getByRole("rowheader", { name: "refund-late" })).toBeInTheDocument();
  });
});

describe("Reliability", () => {
  it("draws one bar per bin, the diagonal and the ECE, and flags overconfident bins", () => {
    const { container } = render(<Reliability bins={BINS} ece={0.045} />);
    expect(screen.getByText("ECE 4.5%")).toBeInTheDocument();
    expect(container.querySelector('[data-line="diagonal"]')).not.toBeNull();
    const over = container.querySelector('rect[data-bin="0.5-0.7"]');
    const fine = container.querySelector('rect[data-bin="0.9-1.0"]');
    expect(over).toHaveAttribute("fill", "var(--gold)");
    expect(fine).toHaveAttribute("fill", "var(--trace)");
    expect(over?.querySelector("title")?.textContent).toBe("0.5-0.7: said 60.0%, right 50.0%, n=10");
  });

  it("still draws an axis with no bins", () => {
    const { container } = render(<Reliability bins={[]} ece={0} />);
    expect(container.querySelectorAll("rect[data-bin]")).toHaveLength(0);
    expect(screen.getByRole("img", { name: "reliability diagram" })).toBeInTheDocument();
  });
});

describe("ContractTable", () => {
  it("shows gate, latest, tolerance, signals, runs and the simulator tag for a system", () => {
    render(<ContractTable contracts={[contractSummary("refund-agent"), blockedSummary("triage-bot")]} />);
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    const first = within(rows[0] as HTMLElement);
    expect(first.getByRole("link", { name: "refund-agent" })).toHaveAttribute("href", "/contract/?name=refund-agent");
    expect(first.getByText("pass")).toBeInTheDocument();
    expect(first.getByText("stable")).toBeInTheDocument();
    expect(first.getByText("simulator")).toBeInTheDocument();
    const second = within(rows[1] as HTMLElement);
    expect(second.getByText("block")).toBeInTheDocument();
    expect(second.getByText("31.0%")).toBeInTheDocument();
    expect(second.getByText("simulator")).toBeInTheDocument();
  });

  it("encodes names in links, says warming for a cold chart and never run for an unrun contract", () => {
    render(
      <ContractTable
        contracts={[contractSummary("a b", { latest: null, chart_warm: false, runs: 0, trend: [] })]}
      />,
    );
    expect(screen.getByRole("link", { name: "a b" })).toHaveAttribute("href", "/contract/?name=a%20b");
    expect(screen.getByText("warming")).toBeInTheDocument();
    expect(screen.getByText("never run")).toBeInTheDocument();
    expect(screen.getAllByText("no runs")).toHaveLength(2);
    expect(screen.queryByText("simulator")).toBeNull();
    expect(screen.getAllByText("—")).toHaveLength(2);
  });
});
