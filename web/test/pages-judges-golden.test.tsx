import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import GoldenPage from "@/app/golden/page";
import JudgesPage from "@/app/judges/page";
import { goldenDetail, goldenSummary, judges } from "./fixtures";
import { fail, mockApi, ok } from "./helpers";

const JUDGES = "GET /api/v1/judges/calibration";
const CALIBRATE = "POST /api/v1/judges/calibration";
const PANEL = "POST /api/v1/judges/panel";
const GOLDEN = "GET /api/v1/golden";

async function paste(label: string, text: string) {
  const box = screen.getByLabelText(label);
  await userEvent.click(box);
  await userEvent.paste(text);
}

describe("Judges page", () => {
  it("shows the standard, each judge's standing, latest agreement and kappa", async () => {
    mockApi({ [JUDGES]: ok(judges()) });
    render(<JudgesPage />);
    expect(await screen.findByText("judge-a")).toBeInTheDocument();
    expect(screen.getByText(/12 labelled anchor items from/)).toHaveTextContent('"clean" and "planted"');
    expect(screen.getByText(/fewer than 80% of them/)).toBeInTheDocument();
    expect(screen.getByText(/last 5 rounds/)).toBeInTheDocument();
    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0] as HTMLElement).getByText("active")).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText("100.0%")).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText("1.00")).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("quarantined · below the agreement floor")).toHaveClass("block");
    expect(within(rows[1] as HTMLElement).getByText("1 run")).toBeInTheDocument();
  });

  it("an unknown quarantine reason is shown as it came and a missing one leaves the badge bare", async () => {
    const base = judges();
    const [a, b] = base.judges;
    mockApi({
      [JUDGES]: ok(
        judges({
          judges: [
            { ...a!, judge: "j-odd", quarantined: true, reason: "manual_hold" },
            { ...b!, judge: "j-null", quarantined: true, reason: null },
          ],
        }),
      ),
    });
    render(<JudgesPage />);
    expect(await screen.findByText("quarantined · manual_hold")).toBeInTheDocument();
    expect(screen.getByText("quarantined · no reason recorded")).toHaveClass("block");
  });

  it("no judges says so and still offers both forms", async () => {
    mockApi({ [JUDGES]: ok(judges({ judges: [] })) });
    render(<JudgesPage />);
    expect(await screen.findByText("No judge has been calibrated yet")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByLabelText("Verdicts JSON")).toBeInTheDocument();
    expect(screen.getByLabelText("Votes JSON")).toBeInTheDocument();
  });

  it("a failed read shows the error and neither the table nor the forms", async () => {
    mockApi({ [JUDGES]: fail(500, "store unavailable") });
    render(<JudgesPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("store unavailable");
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByLabelText("Judge name")).toBeNull();
    expect(screen.queryByText("The standard")).toBeNull();
  });

  it("on 401 it asks for the token and retries with it", async () => {
    const mock = mockApi({ [JUDGES]: [fail(401, "no token"), ok(judges())] });
    render(<JudgesPage />);
    await userEvent.type(await screen.findByLabelText("API token"), "tok-j");
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(await screen.findByText("judge-a")).toBeInTheDocument();
    expect(mock.to(JUDGES)[1]?.authorization).toBe("Bearer tok-j");
  });

  it("the verdict box suggests the anchor ids and labels as its example", async () => {
    mockApi({ [JUDGES]: ok(judges()) });
    render(<JudgesPage />);
    await screen.findByText("judge-a");
    expect(screen.getByLabelText("Verdicts JSON")).toHaveAttribute("placeholder", '{"a1": "clean", "a2": "planted"}');
  });

  it("the example repeats the only label when there is just one", async () => {
    mockApi({ [JUDGES]: ok(judges({ anchors: { count: 2, labels: ["clean"], ids: ["x", "y"], source: "s" } })) });
    render(<JudgesPage />);
    await screen.findByText("judge-a");
    expect(screen.getByLabelText("Verdicts JSON")).toHaveAttribute("placeholder", '{"x": "clean", "y": "clean"}');
  });

  describe("calibration form", () => {
    async function setup(extra: Parameters<typeof mockApi>[0] = {}) {
      const mock = mockApi({ [JUDGES]: ok(judges()), ...extra });
      render(<JudgesPage />);
      await screen.findByText("judge-a");
      return mock;
    }
    const score = () => screen.getByRole("button", { name: "Score against anchors" });

    it("stays disabled until both a judge name and verdicts are given", async () => {
      await setup();
      expect(score()).toBeDisabled();
      await userEvent.type(screen.getByLabelText("Judge name"), "judge-c");
      expect(score()).toBeDisabled();
      await paste("Verdicts JSON", '{"a1": "clean"}');
      expect(score()).toBeEnabled();
    });

    it.each([
      ["{oops", "That is not valid JSON."],
      ["[1, 2]", "Expected a JSON object."],
      ["{}", "The object is empty."],
      ['{"a1": 3}', "Every value must be a label in quotes."],
    ])("rejects %s with its own message before any request is made", async (text, message) => {
      const mock = await setup();
      await userEvent.type(screen.getByLabelText("Judge name"), "judge-c");
      await paste("Verdicts JSON", text);
      await userEvent.click(score());
      expect(screen.getByRole("alert")).toHaveTextContent(message);
      expect(mock.to(CALIBRATE)).toHaveLength(0);
    });

    it("records a round, shows agreement, interval, kappa and standing, and reloads the table", async () => {
      const mock = await setup({
        [CALIBRATE]: ok({ judge: "judge-c", round: 1, n: 12, agree: 11, rate: 0.9167, kappa: 0.83, quarantined: false, reason: null, low: 0.65, high: 0.99 }),
      });
      await userEvent.type(screen.getByLabelText("Judge name"), "  judge-c  ");
      await paste("Verdicts JSON", '{"a1": "clean", "a2": "planted"}');
      await userEvent.click(score());
      const line = await screen.findByText(/Round 1: agreed on 11 of 12/);
      expect(line).toHaveTextContent("91.7%");
      expect(line).toHaveTextContent("95% interval 65.0% to 99.0%");
      expect(line).toHaveTextContent("kappa 0.83");
      expect(line).toHaveTextContent("In good standing.");
      expect(line).toHaveClass("ok");
      expect(mock.to(CALIBRATE)[0]?.body).toEqual({ judge: "judge-c", verdicts: { a1: "clean", a2: "planted" } });
      await waitFor(() => expect(mock.to(JUDGES)).toHaveLength(2));
    });

    it("a quarantined round names the reason in words", async () => {
      await setup({
        [CALIBRATE]: ok({ judge: "j", round: 2, n: 12, agree: 6, rate: 0.5, kappa: 0.1, quarantined: true, reason: "drift", low: 0.25, high: 0.75 }),
      });
      await userEvent.type(screen.getByLabelText("Judge name"), "j");
      await paste("Verdicts JSON", '{"a1": "clean"}');
      await userEvent.click(score());
      const line = await screen.findByText(/Round 2/);
      expect(line).toHaveClass("err");
      expect(line).toHaveTextContent("Quarantined: drifted from its own baseline.");
    });

    it("a quarantine reason it has no words for is shown raw, and a missing one still says quarantined", async () => {
      await setup({
        [CALIBRATE]: [
          ok({ judge: "j", round: 3, n: 12, agree: 6, rate: 0.5, kappa: 0.1, quarantined: true, reason: "manual_hold", low: 0.25, high: 0.75 }),
          ok({ judge: "j", round: 4, n: 12, agree: 6, rate: 0.5, kappa: 0.1, quarantined: true, reason: null, low: 0.25, high: 0.75 }),
        ],
      });
      await userEvent.type(screen.getByLabelText("Judge name"), "j");
      await paste("Verdicts JSON", '{"a1": "clean"}');
      await userEvent.click(score());
      expect(await screen.findByText(/Quarantined: manual_hold\./)).toBeInTheDocument();
      await userEvent.click(score());
      expect(await screen.findByText(/Round 4/)).toHaveTextContent("Quarantined: no reason recorded.");
    });

    it("shows the API's message when the round is refused and clears the earlier result", async () => {
      await setup({
        [CALIBRATE]: [
          ok({ judge: "j", round: 1, n: 12, agree: 12, rate: 1, kappa: 1, quarantined: false, reason: null, low: 0.8, high: 1 }),
          fail(422, "verdicts missing anchor a2"),
        ],
      });
      await userEvent.type(screen.getByLabelText("Judge name"), "j");
      await paste("Verdicts JSON", '{"a1": "clean"}');
      await userEvent.click(score());
      await screen.findByText(/Round 1/);
      await userEvent.click(score());
      expect(await screen.findByRole("alert")).toHaveTextContent("verdicts missing anchor a2");
      expect(screen.queryByText(/Round 1/)).toBeNull();
    });
  });

  describe("panel form", () => {
    async function setup(extra: Parameters<typeof mockApi>[0] = {}) {
      const mock = mockApi({ [JUDGES]: ok(judges()), ...extra });
      render(<JudgesPage />);
      await screen.findByText("judge-a");
      return mock;
    }
    const decide = () => screen.getByRole("button", { name: "Decide" });

    it("stays disabled until votes are given", async () => {
      await setup();
      expect(decide()).toBeDisabled();
      await paste("Votes JSON", '{"judge-a": "clean"}');
      expect(decide()).toBeEnabled();
    });

    it.each([
      ["nope", "That is not valid JSON."],
      ["[]", "Expected a JSON object."],
      ["{}", "The object is empty."],
      ['{"judge-a": true}', "Every value must be a label in quotes."],
    ])("rejects %s with its own message before any request is made", async (text, message) => {
      const mock = await setup();
      await paste("Votes JSON", text);
      await userEvent.click(decide());
      expect(screen.getByRole("alert")).toHaveTextContent(message);
      expect(mock.to(PANEL)).toHaveLength(0);
    });

    it("a verdict names counted and excluded judges", async () => {
      const mock = await setup({
        [PANEL]: ok({
          label: "clean",
          reason: "2 of 2 counted judges agree",
          counted: ["judge-a", "judge-c"],
          excluded: ["judge-b"],
          judges: { "judge-a": "active", "judge-c": "active", "judge-b": "below_floor", "judge-d": "mystery" },
        }),
      });
      await paste("Votes JSON", '{"judge-a": "clean", "judge-b": "planted", "judge-c": "clean"}');
      await userEvent.click(decide());
      const result = await screen.findByTestId("panel-result");
      expect(result).toHaveTextContent("Verdict: clean");
      expect(result).toHaveTextContent("2 of 2 counted judges agree");
      expect(result).toHaveTextContent("judge-a: counted");
      expect(result).toHaveTextContent("judge-b: excluded, below the agreement floor");
      expect(result).toHaveTextContent("judge-d: excluded, mystery");
      expect(mock.to(PANEL)[0]?.body).toEqual({ votes: { "judge-a": "clean", "judge-b": "planted", "judge-c": "clean" } });
    });

    it("a null label prints No verdict", async () => {
      await setup({
        [PANEL]: ok({ label: null, reason: "tie", counted: ["judge-a", "judge-c"], excluded: [], judges: { "judge-a": "active", "judge-c": "active" } }),
      });
      await paste("Votes JSON", '{"judge-a": "clean", "judge-c": "planted"}');
      await userEvent.click(decide());
      const result = await screen.findByTestId("panel-result");
      expect(result).toHaveTextContent("No verdict");
      expect(result).not.toHaveTextContent("Verdict:");
      expect(result).toHaveTextContent("tie");
    });

    it("shows the API's message on failure and no result", async () => {
      await setup({ [PANEL]: fail(409, "no calibrated judge") });
      await paste("Votes JSON", '{"judge-z": "clean"}');
      await userEvent.click(decide());
      expect(await screen.findByRole("alert")).toHaveTextContent("no calibrated judge");
      expect(screen.queryByTestId("panel-result")).toBeNull();
    });
  });
});

describe("Golden page", () => {
  it("an empty list says there are no reports and shows no selector", async () => {
    const mock = mockApi({ [GOLDEN]: ok({ reports: [] }) });
    render(<GoldenPage />);
    expect(await screen.findByText("No golden-set reports on this instance")).toBeInTheDocument();
    expect(screen.queryByLabelText("Golden-set contract")).toBeNull();
    expect(mock.calls).toHaveLength(1);
  });

  it("a failed list shows the error and no selector", async () => {
    mockApi({ [GOLDEN]: fail(500, "reports folder unreadable") });
    render(<GoldenPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("reports folder unreadable");
    expect(screen.queryByLabelText("Golden-set contract")).toBeNull();
  });

  it("loads the first report, shows the numbers and the scope of what they mean", async () => {
    const mock = mockApi({
      [GOLDEN]: ok({ reports: [goldenSummary("triage"), goldenSummary("refunds")] }),
      "GET /api/v1/golden/triage": ok(goldenDetail("triage")),
    });
    render(<GoldenPage />);
    expect(await screen.findByText("Scope of these numbers")).toBeInTheDocument();
    expect(mock.to("GET /api/v1/golden/refunds")).toHaveLength(0);
    expect(screen.getByRole("option", { name: "triage · model-x" })).toBeInTheDocument();
    const gate = screen.getByText("Gate").closest(".stat") as HTMLElement;
    expect(gate).toHaveClass("good");
    expect(gate).toHaveTextContent("pass");
    expect(screen.getByText("Golden items").closest(".stat")).toHaveTextContent("3 runs each");
    expect(screen.getByText("Latency p50 / p95").closest(".stat")).toHaveTextContent("812 / 1904");
    expect(screen.getByText("Cost of the run").closest(".stat")).toHaveTextContent("$0.0123");
    expect(screen.getByText("Cost of the run").closest(".stat")).toHaveTextContent("5400 input tokens");
    expect(screen.getByText("recall")).toBeInTheDocument();
    expect(screen.getByText("95.0%")).toBeInTheDocument();
    expect(screen.getByText("false positive rate")).toBeInTheDocument();
    expect(screen.getByText("clean 20 · planted 10")).toBeInTheDocument();
    expect(screen.getByText("min recall")).toBeInTheDocument();
    expect(screen.getByText("90.0%")).toBeInTheDocument();
    expect(screen.getByText(/2026-11-01 10:00Z/)).toBeInTheDocument();
  });

  it("a failing run is shown as block", async () => {
    mockApi({
      [GOLDEN]: ok({ reports: [goldenSummary("triage", { passed: false })] }),
      "GET /api/v1/golden/triage": ok(goldenDetail("triage", { run: { ...goldenDetail("triage").run, passed: false } })),
    });
    render(<GoldenPage />);
    const gate = (await screen.findByText("Gate")).closest(".stat") as HTMLElement;
    expect(gate).toHaveClass("bad");
    expect(gate).toHaveTextContent("block");
  });

  it("switching the select loads the other report", async () => {
    const mock = mockApi({
      [GOLDEN]: ok({ reports: [goldenSummary("triage"), goldenSummary("refunds", { model: "model-y" })] }),
      "GET /api/v1/golden/triage": ok(goldenDetail("triage")),
      "GET /api/v1/golden/refunds": ok(
        goldenDetail("refunds", { run: { ...goldenDetail("refunds").run, model: "model-y", probes: 77 } }),
      ),
    });
    render(<GoldenPage />);
    await screen.findByText("Scope of these numbers");
    expect(screen.getByText(/one golden set of 30 items/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Golden-set contract"), "refunds");
    expect(await screen.findByText(/one golden set of 77 items/)).toBeInTheDocument();
    expect(screen.getByText("model-y", { selector: "code" })).toBeInTheDocument();
    expect(mock.to("GET /api/v1/golden/refunds")).toHaveLength(1);
    expect(screen.queryByText(/one golden set of 30 items/)).toBeNull();
  });

  it("a report with calibration null says there is no calibration report and draws no diagram", async () => {
    mockApi({
      [GOLDEN]: ok({ reports: [goldenSummary("triage")] }),
      "GET /api/v1/golden/triage": ok(goldenDetail("triage", { calibration: null })),
    });
    render(<GoldenPage />);
    expect(await screen.findByText("No calibration report")).toBeInTheDocument();
    expect(screen.getByText("seismo calibrate --contract triage")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "reliability diagram" })).toBeNull();
  });

  it("calibration present draws the reliability diagram with its ECE", async () => {
    mockApi({
      [GOLDEN]: ok({ reports: [goldenSummary("triage")] }),
      "GET /api/v1/golden/triage": ok(goldenDetail("triage")),
    });
    render(<GoldenPage />);
    expect(await screen.findByRole("img", { name: "reliability diagram" })).toBeInTheDocument();
    expect(screen.getByText("ECE 4.5%")).toBeInTheDocument();
    expect(screen.queryByText("No calibration report")).toBeNull();
  });

  it("drift present renders the agreement table, the chart and the same-served-build sentence", async () => {
    mockApi({
      [GOLDEN]: ok({ reports: [goldenSummary("triage")] }),
      "GET /api/v1/golden/triage": ok(goldenDetail("triage")),
    });
    render(<GoldenPage />);
    expect(await screen.findByText(/Drift · model-x against model-x-next/)).toBeInTheDocument();
    expect(screen.getByText("98.76%")).toBeInTheDocument();
    expect(screen.getByText(/Both names resolved to the same served build \(model-x-2026-05\)/)).toBeInTheDocument();
    expect(screen.getByText("is refund eligible")).toBeInTheDocument();
    expect(screen.getByText("99.00%")).toBeInTheDocument();
    expect(screen.getByText("0.0123")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Disagreement per batch of 10 items control chart" })).toBeInTheDocument();
    expect(screen.getByText("in control")).toBeInTheDocument();
  });

  it("different served builds are named instead", async () => {
    const base = goldenDetail("triage");
    mockApi({
      [GOLDEN]: ok({ reports: [goldenSummary("triage")] }),
      "GET /api/v1/golden/triage": ok(goldenDetail("triage", { drift: { ...base.drift!, model_b_served: "model-x-2026-08" } })),
    });
    render(<GoldenPage />);
    expect(await screen.findByText(/Served builds: model-x-2026-05 and model-x-2026-08/)).toBeInTheDocument();
    expect(screen.queryByText(/Both names resolved/)).toBeNull();
  });

  it("a drift chart with no judged points is cold, not in control", async () => {
    const base = goldenDetail("triage");
    mockApi({
      [GOLDEN]: ok({ reports: [goldenSummary("triage")] }),
      "GET /api/v1/golden/triage": ok(
        goldenDetail("triage", { drift: { ...base.drift!, control_chart: { ...base.drift!.control_chart, points: [] } } }),
      ),
    });
    const { container } = render(<GoldenPage />);
    expect(await screen.findByText("warming · 0 more runs")).toBeInTheDocument();
    expect(container.querySelector('[data-line="ucl"]')).toBeNull();
  });

  it("drift null shows no drift section", async () => {
    mockApi({
      [GOLDEN]: ok({ reports: [goldenSummary("triage")] }),
      "GET /api/v1/golden/triage": ok(goldenDetail("triage", { drift: null })),
    });
    render(<GoldenPage />);
    await screen.findByText("Scope of these numbers");
    expect(screen.queryByText(/Drift ·/)).toBeNull();
    expect(screen.queryByText("Mean total variation")).toBeNull();
  });

  it("a report that cannot be read shows the error and none of its numbers, but keeps the selector", async () => {
    mockApi({
      [GOLDEN]: ok({ reports: [goldenSummary("triage")] }),
      "GET /api/v1/golden/triage": fail(404, "report file is gone"),
    });
    render(<GoldenPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("report file is gone");
    expect(screen.getByLabelText("Golden-set contract")).toBeInTheDocument();
    expect(screen.queryByText("Scope of these numbers")).toBeNull();
    expect(screen.queryByText("Gate")).toBeNull();
  });
});
