import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { createElement } from "react";
import generated from "@/lib/published.generated.json";
import { Limits, OperatingCurve } from "@/components/Published";

type Row = Record<string, string>;
interface Published {
  limits: string;
  shift: Row[];
  drift: Row[];
  flake: Row[];
  falseAlarm: { rate: number; low: number; high: number };
  design: string;
  embedder: string;
}
interface Script {
  limitsSentence: (md: string) => string;
  tableAfter: (md: string, heading: string) => Row[];
  falseAlarmRate: (md: string) => { rate: number; low: number; high: number };
  published: (evalMd: string, report: string) => Published;
  llmsTxt: (data: Published) => string;
}

// A variable specifier keeps tsc from asking for types for a plain .mjs script.
const scriptPath = "../scripts/published.mjs";
const script = (await import(/* @vite-ignore */ scriptPath)) as Script;

const repo = resolve(__dirname, "..", "..");
const evalMd = readFileSync(resolve(repo, "EVAL.md"), "utf8");
const reportMd = readFileSync(resolve(repo, "eval_report.md"), "utf8");

describe("limitsSentence", () => {
  it("returns the block between the markers with whitespace collapsed", () => {
    expect(script.limitsSentence("a\n<!-- LIMITS -->\n  one   two\nthree \n<!-- /LIMITS -->\nb")).toBe("one two three");
  });

  it("fails loudly when EVAL.md has no LIMITS block", () => {
    expect(() => script.limitsSentence("# nothing here")).toThrow("EVAL.md has no <!-- LIMITS --> block");
  });
});

describe("tableAfter", () => {
  const md = ["## Alpha", "", "| name | n |", "|---|---|", "| a | 1 |", "| b | 2 |", "", "| later | x |", "## Beta", "no table"].join("\n");

  it("reads the first table after the heading as rows keyed by the header", () => {
    expect(script.tableAfter(md, "## Alpha")).toEqual([
      { name: "a", n: "1" },
      { name: "b", n: "2" },
    ]);
  });

  it("handles CRLF line endings", () => {
    expect(script.tableAfter(md.replaceAll("\n", "\r\n"), "## Alpha")).toHaveLength(2);
  });

  it("fails when the section is missing", () => {
    expect(() => script.tableAfter(md, "## Gamma")).toThrow('eval_report.md has no section "## Gamma"');
  });

  it("fails when the section has no table", () => {
    expect(() => script.tableAfter(md, "## Beta")).toThrow('section "## Beta" has no table');
  });
});

describe("falseAlarmRate", () => {
  it("parses the rate and its interval", () => {
    expect(script.falseAlarmRate("- false alarm rate: **0.0167** (95% CI 0.0108-0.0256)")).toEqual({
      rate: 0.0167,
      low: 0.0108,
      high: 0.0256,
    });
  });

  it("fails when the line is missing", () => {
    expect(() => script.falseAlarmRate("nothing")).toThrow("eval_report.md has no false alarm rate line");
  });
});

describe("published", () => {
  it("assembles every part from the repository's own eval files", () => {
    const data = script.published(evalMd, reportMd);
    expect(data.limits).toBe(script.limitsSentence(evalMd));
    expect(data.shift.length).toBeGreaterThan(0);
    expect(data.drift.length).toBeGreaterThan(0);
    expect(data.flake.length).toBeGreaterThan(0);
    expect(data.falseAlarm.rate).toBeGreaterThan(0);
    expect(data.design).toMatch(/^baseline/);
    expect(data.embedder).toMatch(/^hashing/);
  });

  it("uses an empty design and embedder when the report omits them", () => {
    const stripped = reportMd.replace(/^design: .+$/m, "").replace(/^embedder: .+$/m, "");
    const data = script.published(evalMd, stripped);
    expect(data.design).toBe("");
    expect(data.embedder).toBe("");
  });

  it("matches what the build generated for the page", () => {
    expect(generated).toEqual(script.published(evalMd, reportMd));
  });
});

describe("llmsTxt", () => {
  it("carries the limits sentence verbatim and names who decides", () => {
    const data = script.published(evalMd, reportMd);
    const text = script.llmsTxt(data);
    expect(text).toContain(data.limits);
    expect(text).toContain("Deterministic code computes every metric");
    expect(text.startsWith("# Seismograph")).toBe(true);
  });
});

describe("the published components", () => {
  it("Limits shows the EVAL.md sentence exactly as the script reads it", () => {
    render(createElement(Limits));
    expect(screen.getByTestId("limits")).toHaveTextContent(script.limitsSentence(evalMd), { normalizeWhitespace: true });
  });

  it("OperatingCurve prints every row of the three tables, misses included, and the false alarm rate", () => {
    const { container } = render(createElement(OperatingCurve));
    const data = script.published(evalMd, reportMd);
    expect(container.querySelectorAll("table")).toHaveLength(3);
    const rows = container.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(data.shift.length + data.drift.length + data.flake.length);
    for (const row of data.shift) expect(container).toHaveTextContent(`${row["95% CI"]}`);
    expect(container).toHaveTextContent(`False alarm rate ${data.falseAlarm.rate}`);
    expect(container).toHaveTextContent(data.embedder);
  });
});
