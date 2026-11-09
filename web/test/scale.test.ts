import { describe, expect, it } from "vitest";
import { linear, niceCeil, polyline, round, stack, ticks, trace, yCeiling } from "@/lib/scale";

describe("linear", () => {
  it("maps the domain onto the range, inverted ranges included", () => {
    const y = linear(0, 1, 200, 0);
    expect(y(0)).toBe(200);
    expect(y(0.25)).toBe(150);
    expect(y(1)).toBe(0);
  });

  it("maps a zero-width domain to the middle of the range instead of dividing by zero", () => {
    expect(linear(5, 5, 0, 100)(5)).toBe(50);
  });
});

describe("niceCeil", () => {
  it.each([
    [0.07, 0.1],
    [0.11, 0.2],
    [0.31, 0.5],
    [0.62, 1],
    [1, 1],
    [3, 5],
    [7, 10],
  ])("rounds %f up to %f", (value, expected) => {
    expect(niceCeil(value)).toBe(expected);
  });

  it("falls back to 1 for zero, negatives and NaN so an empty chart still has an axis", () => {
    expect(niceCeil(0)).toBe(1);
    expect(niceCeil(-2)).toBe(1);
    expect(niceCeil(Number.NaN)).toBe(1);
  });
});

describe("ticks and ceilings", () => {
  it("spaces ticks evenly from zero to the ceiling", () => {
    expect(ticks(0.2)).toEqual([0, 0.05, 0.1, 0.15, 0.2]);
    expect(ticks(1, 2)).toEqual([0, 0.5, 1]);
  });

  it("gives the tallest value or limit 15% of headroom", () => {
    expect(yCeiling([0.1, 0.4], [0.22])).toBe(0.5);
    expect(yCeiling([0.1], [0.9])).toBe(2);
    expect(yCeiling([], [])).toBe(1);
  });
});

describe("paths", () => {
  it("rounds to two decimals and joins points for an SVG polyline", () => {
    expect(round(1.23456)).toBe(1.23);
    expect(polyline([[0, 1.005], [10.129, 2]])).toBe("0,1 10.13,2");
  });

  it("draws a flat line for an empty series", () => {
    expect(trace([], 100, 40, 1)).toBe("0,20 100,20");
  });

  it("swings the pen further for larger values and never past the strip", () => {
    const quiet = trace([0.01], 100, 40, 1);
    const loud = trace([0.9], 100, 40, 1);
    const peak = (path: string) => Math.min(...path.split(" ").map((p) => Number(p.split(",")[1])));
    expect(peak(loud)).toBeLessThan(peak(quiet));
    expect(peak(trace([5], 100, 40, 1))).toBeGreaterThanOrEqual(0);
    expect(trace([0.5], 100, 40, 0).split(" ")).toHaveLength(5);
  });

  it("is deterministic", () => {
    expect(trace([0.1, 0.4, 0.2], 300, 60, 0.5)).toBe(trace([0.1, 0.4, 0.2], 300, 60, 0.5));
  });
});

describe("stack", () => {
  it("stacks shares in the given order and treats an absent mode as zero height", () => {
    expect(stack({ a: 0.75, b: 0.25 }, ["a", "missing", "b"])).toEqual([
      { key: "a", y0: 0, y1: 0.75 },
      { key: "missing", y0: 0.75, y1: 0.75 },
      { key: "b", y0: 0.75, y1: 1 },
    ]);
  });
});
