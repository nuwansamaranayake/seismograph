// Regression tests for the defects an independent review reproduced on 2026-11-09.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { InvariantMatrix } from "@/components/InvariantMatrix";
import { ModeRiver } from "@/components/Modes";
import { Reliability } from "@/components/Reliability";
import type { CalibrationBin, ModeCell } from "@/lib/types";
import { matrixRow, mode } from "./fixtures";

describe("ModeRiver with a mode that fell out of the pooled window", () => {
  // Twenty runs were recorded. The pooled window holds the last twelve, which only ever
  // answered "usual". Run 2 also answered "old" one time in ten.
  const cell: ModeCell = {
    probe: "refund-basic",
    perturbation: "repeat_run",
    window: 12,
    pooled: {
      n: 240,
      modes: [mode("usual", 1, { count: 240 })],
      second_mode_share: 0,
      second_mode_low: 0,
      second_mode_detected: false,
    },
    by_run: [
      { run_id: 1, t: 1, n: 20, shares: { usual: 1 } },
      { run_id: 2, t: 2, n: 20, shares: { usual: 0.9, old: 0.1 } },
      { run_id: 3, t: 3, n: 20, shares: { usual: 1 } },
    ],
  };

  it("still draws that mode, so the run's column reaches 100%", () => {
    const { container } = render(<ModeRiver cell={cell} noiseFloor={0.02} />);
    const old = container.querySelectorAll('rect[data-mode="old"]');
    expect(old).toHaveLength(1);
    const heights = (key: string) =>
      [...container.querySelectorAll(`rect[data-mode="${key}"]`)].map((r) => Number(r.getAttribute("height")));
    const full = heights("usual")[0]!;
    // run 2: the two bands together are as tall as a full column
    expect(heights("usual")[1]! + heights("old")[0]!).toBeCloseTo(full, 1);
  });

  it("says a mode is drawn without a legend entry, and why", () => {
    render(<ModeRiver cell={cell} noiseFloor={0.02} />);
    expect(screen.getByText(/1 more mode appear only in runs before the last 12/)).toBeInTheDocument();
  });

  it("says nothing extra when every mode is in the pooled window", () => {
    const current = { ...cell, by_run: cell.by_run.filter((run) => run.run_id !== 2) };
    render(<ModeRiver cell={current} noiseFloor={0.02} />);
    expect(screen.queryByText(/more mode/)).not.toBeInTheDocument();
  });
});

describe("Reliability with empty bins", () => {
  const filled: CalibrationBin[] = [
    { bin: "0.8-0.9", count: 10, accuracy: 0.7, mean_confidence: 0.85, abs_gap: 0.15 },
    { bin: "0.9-1.0", count: 30, accuracy: 0.95, mean_confidence: 0.96, abs_gap: 0.01 },
  ];
  const empty = (bin: string): CalibrationBin => ({ bin, count: 0, accuracy: null, mean_confidence: null, abs_gap: null });

  it("draws no bar for a bin that held no answers and says so", () => {
    const { container } = render(<Reliability bins={[empty("0.5-0.6"), ...filled]} ece={0.04} />);
    expect(container.querySelector('rect[data-bin="0.5-0.6"]')).toBeNull();
    expect(container.querySelectorAll("rect[data-bin]")).toHaveLength(2);
    expect(screen.getByText("1 confidence bin held no answers and is not drawn.")).toBeInTheDocument();
  });

  it("keeps the axis starting at 50% confidence instead of dragging it to zero", () => {
    const withEmpty = render(<Reliability bins={[empty("0.5-0.6"), ...filled]} ece={0.04} />);
    const x = (c: HTMLElement) => c.querySelector('[data-line="diagonal"]')!.getAttribute("x1");
    const y = (c: HTMLElement) => c.querySelector('[data-line="diagonal"]')!.getAttribute("y1");
    const emptyStart = [x(withEmpty.container), y(withEmpty.container)];
    withEmpty.unmount();
    const without = render(<Reliability bins={filled} ece={0.04} />);
    expect(emptyStart).toEqual([x(without.container), y(without.container)]);
  });

  it("counts several empty bins in the plural and none at all when every bin is filled", () => {
    const { unmount } = render(<Reliability bins={[empty("0.5-0.6"), empty("0.6-0.7"), ...filled]} ece={0.04} />);
    expect(screen.getByText("2 confidence bins held no answers and are not drawn.")).toBeInTheDocument();
    unmount();
    render(<Reliability bins={filled} ece={0.04} />);
    expect(screen.queryByText(/held no answers/)).not.toBeInTheDocument();
  });
});

describe("InvariantMatrix and the second-mode gate", () => {
  it("names the second mode share on a cell that the mode gate blocked", () => {
    render(
      <InvariantMatrix
        rows={[
          matrixRow("refund-basic", "repeat_run", { flip_rate: 0, second_mode_share: 0.12, violated: true }),
          matrixRow("refund-basic", "format"),
        ]}
      />,
    );
    const blocked = screen.getAllByRole("cell").find((cell) => cell.className === "violated")!;
    expect(blocked).toHaveAttribute("title", expect.stringContaining("second mode 12.0%"));
    const held = screen.getAllByRole("cell").find((cell) => cell.className === "held")!;
    expect(held.getAttribute("title")).not.toContain("second mode");
  });
});
