import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import ContractPage from "@/app/contract/page";
import {
  coldChart,
  contractDetail,
  emptyReport,
  matrixRow,
  modeCell,
  paraphraseDetail,
  report,
  secondModeCell,
  seriesPoint,
  simulators,
  warmChart,
} from "./fixtures";
import { fail, mockApi, ok, visit } from "./helpers";

const REPORT = "GET /api/v1/reports/refund-agent";
const DETAIL = "GET /api/v1/contracts/refund-agent";
const SUTS = "GET /api/v1/suts";
const VARIANTS = "POST /api/v1/probes/variants";

function open(routes: Parameters<typeof mockApi>[0]) {
  visit("/contract/?name=refund-agent");
  return mockApi({ [SUTS]: ok({ suts: simulators() }), ...routes });
}

describe("Contract page address handling", () => {
  it("a missing ?name= says no contract is named and makes no request", async () => {
    const mock = mockApi({});
    render(<ContractPage />);
    expect(await screen.findByText("No contract named in the address")).toBeInTheDocument();
    expect(mock.calls).toHaveLength(0);
    expect(screen.getByRole("link", { name: "contracts list" })).toHaveAttribute("href", "/contracts/");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Contract");
  });

  it("an empty ?name= is treated the same way", async () => {
    visit("/contract/?name=");
    const mock = mockApi({});
    render(<ContractPage />);
    expect(await screen.findByText("No contract named in the address")).toBeInTheDocument();
    expect(mock.calls).toHaveLength(0);
  });

  it("encodes the name it asks for", async () => {
    visit("/contract/?name=a%20b");
    const mock = mockApi({ "GET /api/v1/reports/a%20b": ok(report({ contract: "a b" })), "GET /api/v1/contracts/a%20b": ok(contractDetail({ name: "a b" })), [SUTS]: ok({ suts: simulators() }) });
    render(<ContractPage />);
    expect(await screen.findByRole("heading", { level: 1, name: "a b" })).toBeInTheDocument();
    await screen.findByText(/The contract · /);
    expect(mock.to("GET /api/v1/reports/a%20b")).toHaveLength(1);
  });
});

describe("Contract page board", () => {
  it("shows gate, tolerances, plan, both control charts, the matrix, the history and the definition", async () => {
    open({ [REPORT]: ok(report()), [DETAIL]: ok(contractDetail()) });
    render(<ContractPage />);
    expect(await screen.findByRole("img", { name: "Worst flip rate per run (X chart) control chart" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Malformed output per run (p chart) control chart" })).toBeInTheDocument();
    expect(screen.getByText("tolerance · flip 10.0%")).toBeInTheDocument();
    expect(screen.getByText("malformed 5.0%")).toBeInTheDocument();
    expect(screen.getByText("plan plan-abc123")).toBeInTheDocument();
    expect(screen.getByText("3 runs")).toBeInTheDocument();
    expect(screen.getAllByText(/gate tolerance 10\.0%/).length).toBeGreaterThan(0);
    expect(screen.getByText("Invariant matrix · latest run")).toBeInTheDocument();
    expect(await screen.findByText(/The contract · 20 samples per cell · 1 cells/)).toBeInTheDocument();
    expect(screen.getByText(/contract: refund-agent/)).toBeInTheDocument();
  });

  it("run history lists newest first, links each run, tags the simulator and gives the reason", async () => {
    open({ [REPORT]: ok(report()), [DETAIL]: ok(contractDetail()) });
    render(<ContractPage />);
    await screen.findByText("Run history");
    const table = screen.getByText("Run history").closest(".card") as HTMLElement;
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(within(rows[0] as HTMLElement).getByRole("link", { name: "2" })).toHaveAttribute("href", "/run/?id=102");
    expect(within(rows[0] as HTMLElement).getByText("block")).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText("flip rate 30.0% over 10.0%")).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText("every declared tolerance held")).toBeInTheDocument();
    for (const row of rows) expect(within(row).getByText("simulator")).toBeInTheDocument();
  });

  it("the launcher defaults to the system of the last run and starts at t = number of runs", async () => {
    open({
      [REPORT]: ok(report({ series: [seriesPoint(0, { sut: "drifting" }), seriesPoint(1, { sut: "drifting" })], runs: 2 })),
      [DETAIL]: ok(contractDetail()),
    });
    render(<ContractPage />);
    const select = await screen.findByLabelText("System under test");
    expect(select).toHaveValue("drifting");
    expect(screen.getByRole("button", { name: "Run from t = 2" })).toBeInTheDocument();
  });

  it("a finished run reloads both the report and the definition", async () => {
    const mock = open({
      [REPORT]: ok(report()),
      [DETAIL]: ok(contractDetail()),
      "POST /api/v1/runs": ok({ run_id: 9, cells: 1, gate: "pass", reasons: [], worst_flip_rate: 0, threshold: 0.1, worst_cell: null, worst_malformed_rate: 0, skipped: [] }),
    });
    render(<ContractPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Run from t = 3" }));
    await waitFor(() => expect(mock.to(REPORT)).toHaveLength(2));
    expect(mock.to(DETAIL)).toHaveLength(2);
  });

  it("lists cells that were not measured", async () => {
    open({ [REPORT]: ok(report({ notes: ["refund-basic / paraphrase: no accepted variants"] })), [DETAIL]: ok(contractDetail()) });
    render(<ContractPage />);
    expect(await screen.findByText("Not measured: refund-basic / paraphrase: no accepted variants")).toBeInTheDocument();
  });

  it("a contract with zero runs shows the launcher and the empty message and no charts", async () => {
    open({ [REPORT]: ok(emptyReport()), [DETAIL]: ok(contractDetail()) });
    render(<ContractPage />);
    expect(await screen.findByText("No runs recorded for this contract")).toBeInTheDocument();
    expect(await screen.findByLabelText("System under test")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run from t = 0" })).toBeInTheDocument();
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.queryByText("Run history")).toBeNull();
    expect(screen.queryByText("Invariant matrix · latest run")).toBeNull();
    expect(screen.getByText("no runs")).toBeInTheDocument();
    expect(screen.getByLabelText("System under test")).toHaveValue("stable");
  });

  it("while the chart is cold the page says how many more runs are needed and draws no limits", async () => {
    const cold = coldChart({ runs_until_warm: 6 });
    open({
      [REPORT]: ok(report({ charts: { flip: cold, malformed: cold } })),
      [DETAIL]: ok(contractDetail()),
    });
    const { container } = render(<ContractPage />);
    expect((await screen.findAllByText("warming · 6 more runs")).length).toBe(2);
    expect(container.querySelector('[data-line="ucl"]')).toBeNull();
    expect(container.querySelector('[data-line="center"]')).toBeNull();
  });

  it("a warm chart with an alarm names the run in its signal text", async () => {
    const flip = warmChart({ points: [{ ...warmChart().points[0]!, alarm: true, rule: "we1", t: 2 }] });
    open({ [REPORT]: ok(report({ charts: { flip, malformed: warmChart() } })), [DETAIL]: ok(contractDetail()) });
    render(<ContractPage />);
    expect(await screen.findByText(/Signal at run 2\./)).toBeInTheDocument();
  });
});

describe("Contract page mode topology", () => {
  it("a single mode cell has no selector", async () => {
    open({ [REPORT]: ok(report()), [DETAIL]: ok(contractDetail()) });
    render(<ContractPage />);
    await screen.findByText(/Mode topology · refund-basic/);
    expect(screen.queryByLabelText("Mode topology of cell")).toBeNull();
  });

  it("no mode cells means no topology card at all", async () => {
    open({ [REPORT]: ok(report({ modes: [] })), [DETAIL]: ok(contractDetail()) });
    render(<ContractPage />);
    await screen.findByText("Run history");
    expect(screen.queryByText(/Mode topology/)).toBeNull();
  });

  it("with several cells the selector defaults to the cell with a detected second mode and can switch", async () => {
    open({
      [REPORT]: ok(
        report({
          modes: [modeCell("refund-basic", "repeat_run"), secondModeCell("refund-basic", "paraphrase"), modeCell("refund-late", "format")],
        }),
      ),
      [DETAIL]: ok(contractDetail()),
    });
    render(<ContractPage />);
    const select = await screen.findByLabelText("Mode topology of cell");
    expect(select).toHaveValue("1");
    expect(screen.getByRole("option", { name: "refund-basic · Paraphrase · second mode" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "refund-late · Format" })).toBeInTheDocument();
    expect(screen.getByText(/Mode topology · refund-basic · Paraphrase/)).toBeInTheDocument();
    expect(screen.getByText("second mode detected")).toBeInTheDocument();
    await userEvent.selectOptions(select, "2");
    expect(screen.getByText(/Mode topology · refund-late · Format/)).toBeInTheDocument();
    expect(screen.getByText("one mode")).toBeInTheDocument();
  });

  it("with several cells and none flagged it starts at the first", async () => {
    open({
      [REPORT]: ok(report({ modes: [modeCell("refund-basic", "repeat_run"), modeCell("refund-late", "format")] })),
      [DETAIL]: ok(contractDetail()),
    });
    render(<ContractPage />);
    expect(await screen.findByLabelText("Mode topology of cell")).toHaveValue("0");
  });
});

describe("Contract page paraphrase card", () => {
  it("is absent when no invariant declares paraphrase", async () => {
    open({ [REPORT]: ok(report()), [DETAIL]: ok(contractDetail()) });
    render(<ContractPage />);
    await screen.findByText(/The contract · /);
    expect(screen.queryByText("Paraphrase variants")).toBeNull();
  });

  it("appears when an invariant declares paraphrase, with a button per probe and no accepted variants on record", async () => {
    open({ [REPORT]: ok(report()), [DETAIL]: ok(paraphraseDetail()) });
    render(<ContractPage />);
    expect(await screen.findByText("Paraphrase variants")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate for refund-basic" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate for refund-late" })).toBeInTheDocument();
    expect(screen.getByText(/No accepted variants on record/)).toBeInTheDocument();
  });

  it("counts accepted variants, singular and plural", async () => {
    const variant = { probe: "refund-basic", perturbation: "paraphrase", text: "t", back_check_score: 0.9, accepted: true };
    open({ [REPORT]: ok(report()), [DETAIL]: ok(paraphraseDetail({ variants: [variant] })) });
    const { unmount } = render(<ContractPage />);
    expect(await screen.findByText(/1 accepted variant on record\. Paraphrase cells run\./)).toBeInTheDocument();
    unmount();
    open({
      [REPORT]: ok(report()),
      [DETAIL]: ok(paraphraseDetail({ variants: [variant, variant, { ...variant, accepted: false }] })),
    });
    render(<ContractPage />);
    expect(await screen.findByText(/2 accepted variants on record/)).toBeInTheDocument();
  });

  it("generates five variants for the probe, reports the back-check outcome with the rejection reasons, and refreshes", async () => {
    const mock = open({
      [REPORT]: ok(report()),
      [DETAIL]: ok(paraphraseDetail()),
      [VARIANTS]: ok({
        accepted: 3,
        rejected: 2,
        variants: [
          { text: "a", back_check_score: 0.9, accepted: true, reason: "" },
          { text: "b", back_check_score: 0.2, accepted: false, reason: "too different" },
          { text: "c", back_check_score: 0.3, accepted: false, reason: "too different" },
          { text: "d", back_check_score: 0.99, accepted: false, reason: "adds a number" },
        ],
      }),
    });
    render(<ContractPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Generate for refund-late" }));
    expect(await screen.findByText("3 accepted, 2 rejected by the back-check (too different, adds a number).")).toBeInTheDocument();
    expect(mock.to(VARIANTS)[0]?.body).toEqual({ contract: "refund-agent", probe: "refund-late", n: 5 });
    await waitFor(() => expect(mock.to(REPORT)).toHaveLength(2));
    expect(mock.to(DETAIL)).toHaveLength(2);
  });

  it("omits the reason list when every variant was accepted", async () => {
    open({
      [REPORT]: ok(report()),
      [DETAIL]: ok(paraphraseDetail()),
      [VARIANTS]: ok({ accepted: 1, rejected: 0, variants: [{ text: "a", back_check_score: 0.9, accepted: true, reason: "" }] }),
    });
    render(<ContractPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Generate for refund-basic" }));
    expect(await screen.findByText("1 accepted, 0 rejected by the back-check.")).toBeInTheDocument();
  });

  it("shows the 503 message when generation is unavailable and no result", async () => {
    open({
      [REPORT]: ok(report()),
      [DETAIL]: ok(paraphraseDetail()),
      [VARIANTS]: fail(503, "No model is configured on this instance"),
    });
    render(<ContractPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Generate for refund-basic" }));
    expect(await screen.findByText("No model is configured on this instance")).toBeInTheDocument();
    expect(screen.queryByText(/rejected by the back-check/)).toBeNull();
    expect(screen.getByRole("button", { name: "Generate for refund-basic" })).toBeEnabled();
  });
});

describe("Contract page failures", () => {
  it("a failed report shows the error and none of the board, while the definition still shows", async () => {
    open({ [REPORT]: fail(500, "report store is down"), [DETAIL]: ok(contractDetail()) });
    render(<ContractPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("report store is down");
    expect(screen.queryByText("Run history")).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.queryByText("No runs recorded for this contract")).toBeNull();
    expect(screen.queryByRole("button", { name: /Run from/ })).toBeNull();
    expect(await screen.findByText(/The contract · /)).toBeInTheDocument();
  });

  it("an unknown contract shows not found for both reads", async () => {
    open({ [REPORT]: fail(404, "no such contract"), [DETAIL]: fail(404, "no such contract") });
    render(<ContractPage />);
    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(2));
    expect(screen.getAllByText("Not found")).toHaveLength(2);
  });

  it("on 401 the token form appears and the retry carries the token for both reads", async () => {
    const mock = open({
      [REPORT]: [fail(401, "no token"), ok(report())],
      [DETAIL]: [fail(401, "no token"), ok(contractDetail())],
    });
    render(<ContractPage />);
    const inputs = await screen.findAllByLabelText("API token");
    expect(inputs).toHaveLength(2);
    await userEvent.type(inputs[0] as HTMLElement, "tok-9");
    await userEvent.click(screen.getAllByRole("button", { name: "Connect" })[0] as HTMLElement);
    expect(await screen.findByText("Run history")).toBeInTheDocument();
    expect(mock.to(REPORT)[1]?.authorization).toBe("Bearer tok-9");
  });

  it("uses the matrix row the report supplies for the latest run only", async () => {
    open({
      [REPORT]: ok(report({ matrix: [matrixRow("refund-basic", "repeat_run", { flip_rate: 0.3, violated: true })] })),
      [DETAIL]: ok(contractDetail()),
    });
    const { container } = render(<ContractPage />);
    await screen.findByText("Invariant matrix · latest run");
    expect(container.querySelector("table.matrix td.violated")).toHaveTextContent("30.0%");
  });
});
