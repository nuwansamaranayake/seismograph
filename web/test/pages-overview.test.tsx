import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import ContractsPage from "@/app/contracts/page";
import GuidePage from "@/app/guide/page";
import OverviewPage from "@/app/page";
import RunPage from "@/app/run/page";
import { NAV } from "@/components/Shell";
import {
  blockedSummary,
  contractSummary,
  matrixRow,
  mode,
  overview,
  runDetail,
} from "./fixtures";
import { fail, mockApi, ok, visit } from "./helpers";

const OVERVIEW = "GET /api/v1/overview";

function tile(label: string): HTMLElement {
  const found = [...document.querySelectorAll<HTMLElement>(".stat")].find((el) => el.querySelector(".label")?.textContent === label);
  if (!found) throw new Error(`no stat tile named ${label}`);
  return found;
}
const CONTRACTS = "GET /api/v1/contracts";

describe("Overview page", () => {
  it("shows the stat tiles, the contract table and the published limits", async () => {
    mockApi({ [OVERVIEW]: ok(overview()) });
    render(<OverviewPage />);
    expect(await screen.findByText("Runs recorded")).toBeInTheDocument();
    expect(within(tile("Contracts")).getByText("2")).toBeInTheDocument();
    expect(within(tile("Gate passing")).getByText("1")).toBeInTheDocument();
    expect(tile("Gate passing")).toHaveClass("good");
    expect(tile("Gate blocking")).toHaveClass("bad");
    expect(tile("Chart signals")).toHaveClass("bad");
    expect(tile("Cells with a second mode, latest runs")).toHaveClass("warn");
    expect(within(tile("Judges quarantined")).getByText("1 / 3")).toBeInTheDocument();
    expect(tile("Judges quarantined")).toHaveClass("warn");
    expect(screen.getByRole("link", { name: "triage-bot" })).toBeInTheDocument();
    expect(screen.getAllByText("simulator").length).toBeGreaterThan(0);
    expect(screen.getByTestId("limits").textContent).toMatch(/Seismograph detects/);
    expect(screen.getByRole("navigation")).toBeInTheDocument();
  });

  it("draws the trace of the contract with the most chart signals", async () => {
    mockApi({ [OVERVIEW]: ok(overview()) });
    render(<OverviewPage />);
    expect(await screen.findByRole("img", { name: "worst flip rate per run, triage-bot" })).toBeInTheDocument();
    expect(screen.getByText("trace · triage-bot · worst flip rate per run")).toBeInTheDocument();
  });

  it("breaks a tie on signals by the longer trend", async () => {
    mockApi({
      [OVERVIEW]: ok(
        overview({
          latest: [
            contractSummary("short", { trend: [0.1] }),
            contractSummary("long", { trend: [0.1, 0.2, 0.3] }),
          ],
        }),
      ),
    });
    render(<OverviewPage />);
    expect(await screen.findByRole("img", { name: "worst flip rate per run, long" })).toBeInTheDocument();
  });

  it("shows quiet tiles with no tone when nothing is passing, blocked, signalling or quarantined", async () => {
    mockApi({
      [OVERVIEW]: ok(
        overview({
          passing: 0,
          blocked: 0,
          alarms: 0,
          cells_with_second_mode: 0,
          judges: { total: 2, quarantined: 0 },
          latest: [contractSummary("only", { latest: null, runs: 0, trend: [], chart_warm: false })],
        }),
      ),
    });
    render(<OverviewPage />);
    await screen.findByText("Runs recorded");
    for (const label of ["Gate passing", "Gate blocking", "Chart signals", "Cells with a second mode, latest runs", "Judges quarantined"]) {
      const classes = tile(label).className;
      expect(classes).not.toMatch(/good|bad|warn/);
    }
    expect(screen.getByText("no signal recorded yet", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "no signal recorded yet" })).toBeInTheDocument();
  });

  it("zero contracts says so and shows no stat tiles and no table", async () => {
    mockApi({ [OVERVIEW]: ok(overview({ contracts: 0, runs: 0, passing: 0, blocked: 0, alarms: 0, latest: [] })) });
    render(<OverviewPage />);
    expect(await screen.findByText("No contracts registered yet")).toBeInTheDocument();
    expect(screen.queryByText("Runs recorded")).toBeNull();
    expect(screen.queryByText("Gate passing")).toBeNull();
    expect(screen.getByRole("link", { name: "Register a contract" })).toHaveAttribute("href", "/contracts/");
    expect(screen.getByRole("link", { name: "guide" })).toHaveAttribute("href", "/guide/");
  });

  it("an API failure shows the error and none of the board", async () => {
    mockApi({ [OVERVIEW]: fail(500, "database is down") });
    render(<OverviewPage />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("database is down");
    expect(screen.queryByText("Runs recorded")).toBeNull();
    expect(screen.queryByText("Gate passing")).toBeNull();
    expect(screen.queryByRole("link", { name: "triage-bot" })).toBeNull();
    expect(screen.getByRole("img", { name: "no signal recorded yet" })).toBeInTheDocument();
  });

  it("a network failure says the API could not be reached", async () => {
    mockApi({ [OVERVIEW]: { throws: new TypeError("Failed to fetch") } });
    render(<OverviewPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The API could not be reached");
  });

  it("Try again asks the API a second time and then shows the board", async () => {
    const mock = mockApi({ [OVERVIEW]: [fail(503, "warming up"), ok(overview())] });
    render(<OverviewPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Runs recorded")).toBeInTheDocument();
    expect(mock.to(OVERVIEW)).toHaveLength(2);
  });

  it("on 401 it asks for the token, stores it, retries, and the retry carries the Bearer header", async () => {
    const mock = mockApi({ [OVERVIEW]: [fail(401, "Not authenticated"), ok(overview())] });
    render(<OverviewPage />);
    await userEvent.type(await screen.findByLabelText("API token"), "tok-123");
    expect(screen.queryByText("Runs recorded")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(await screen.findByText("Runs recorded")).toBeInTheDocument();
    expect(sessionStorage.getItem("seismograph.token")).toBe("tok-123");
    expect(mock.calls[0]?.authorization).toBeUndefined();
    expect(mock.calls[1]?.authorization).toBe("Bearer tok-123");
    expect(screen.queryByLabelText("API token")).toBeNull();
  });
});

describe("Contracts page", () => {
  it("lists the contracts and offers the editor", async () => {
    mockApi({ [CONTRACTS]: ok({ contracts: [contractSummary("refund-agent"), blockedSummary("triage-bot")] }) });
    render(<ContractsPage />);
    expect(await screen.findByRole("link", { name: "refund-agent" })).toBeInTheDocument();
    expect(screen.getByText("Registered")).toBeInTheDocument();
    expect(screen.getByLabelText("Contract YAML")).toBeInTheDocument();
  });

  it("no contracts says so, shows no table and still offers the editor", async () => {
    mockApi({ [CONTRACTS]: ok({ contracts: [] }) });
    render(<ContractsPage />);
    expect(await screen.findByText("No contracts registered yet")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByLabelText("Contract YAML")).toBeInTheDocument();
  });

  it("an API failure shows the error and no table", async () => {
    mockApi({ [CONTRACTS]: fail(500, "boom") });
    render(<ContractsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText("No contracts registered yet")).toBeNull();
  });

  it("registering a contract refreshes the list", async () => {
    const mock = mockApi({
      [CONTRACTS]: [ok({ contracts: [] }), ok({ contracts: [contractSummary("my-refund-contract")] })],
      "POST /api/v1/contracts": ok({ contract: "my-refund-contract", plan_id: "p", entries: 4 }),
    });
    render(<ContractsPage />);
    await screen.findByText("No contracts registered yet");
    await userEvent.click(screen.getByRole("button", { name: "Register and compile" }));
    expect(await screen.findByText("Registered")).toBeInTheDocument();
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(mock.to(CONTRACTS)).toHaveLength(2);
  });
});

describe("Run page", () => {
  it("a non-numeric id shows the empty message and makes no request", async () => {
    visit("/run/?id=abc");
    const mock = mockApi({});
    render(<RunPage />);
    expect(await screen.findByText("No run named in the address")).toBeInTheDocument();
    expect(mock.calls).toHaveLength(0);
  });

  it("a missing id behaves the same", async () => {
    const mock = mockApi({});
    render(<RunPage />);
    expect(await screen.findByText("No run named in the address")).toBeInTheDocument();
    expect(mock.calls).toHaveLength(0);
  });

  it("a partly numeric id is not a run id", async () => {
    visit("/run/?id=12x");
    const mock = mockApi({});
    render(<RunPage />);
    expect(await screen.findByText("No run named in the address")).toBeInTheDocument();
    expect(mock.calls).toHaveLength(0);
  });

  it("shows the gate decision, reasons, simulator tag with its planted defect, matrix and modes", async () => {
    visit("/run/?id=41");
    mockApi({ "GET /api/v1/runs/41": ok(runDetail()) });
    render(<RunPage />);
    expect(await screen.findByRole("link", { name: "refund-agent" })).toHaveAttribute("href", "/contract/?name=refund-agent");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Run 41");
    expect(screen.getByText("t = 3")).toBeInTheDocument();
    expect(screen.getByText("seed 7")).toBeInTheDocument();
    expect(screen.getByText("embedder hash-embedder")).toBeInTheDocument();
    expect(screen.getByText("2026-11-01 10:00Z")).toBeInTheDocument();
    expect(screen.getByText("Gate decision").closest(".card")).toHaveClass("alarm");
    expect(screen.getByText("flip rate 30.0% over 10.0%")).toBeInTheDocument();
    expect(screen.getByText("drifting")).toBeInTheDocument();
    expect(screen.getByText("simulator")).toBeInTheDocument();
    expect(screen.getByText(/Planted defect: decision flips from t = 4\./)).toBeInTheDocument();
    expect(screen.getByText(/Outcome modes · refund-basic · Repeat run · 20 samples/)).toBeInTheDocument();
    expect(screen.getByText("second mode 30.0%")).toHaveClass("block");
    expect(screen.getByText("Usual answer")).toBeInTheDocument();
  });

  it("a passing run with one mode and no reasons says every tolerance held", async () => {
    visit("/run/?id=42");
    mockApi({
      "GET /api/v1/runs/42": ok(
        runDetail({
          run_id: 42,
          gate: { decision: "pass", worst_flip_rate: 0.02, threshold: 0.1, evidence: {} },
          simulator: { summary: "Stable.", planted_defect: null },
          matrix: [matrixRow("refund-basic", "repeat_run")],
          modes: [
            { probe: "refund-basic", perturbation: "repeat_run", n: 20, modes: [mode("eligible", 1)], second_mode_share: 0, second_mode_detected: false },
          ],
        }),
      ),
    });
    render(<RunPage />);
    expect(await screen.findByText("Every declared tolerance held.")).toBeInTheDocument();
    expect(screen.getByText("Gate decision").closest(".card")).toHaveClass("ok");
    expect(screen.getByText(/No planted defect\./)).toBeInTheDocument();
    expect(screen.getByText("one mode")).toBeInTheDocument();
    expect(screen.getByText("simulator")).toBeInTheDocument();
  });

  it("a second mode below the detection bar is shown without the alarm colour", async () => {
    visit("/run/?id=43");
    mockApi({
      "GET /api/v1/runs/43": ok(
        runDetail({
          modes: [
            {
              probe: "p",
              perturbation: "format",
              n: 20,
              modes: [mode("a", 0.95), mode("b", 0.05)],
              second_mode_share: 0.05,
              second_mode_detected: false,
            },
          ],
        }),
      ),
    });
    render(<RunPage />);
    expect(await screen.findByText("second mode 5.0%")).not.toHaveClass("block");
  });

  it("a run with no stored gate, no simulator record and skipped cells says so plainly", async () => {
    visit("/run/?id=44");
    mockApi({
      "GET /api/v1/runs/44": ok(
        runDetail({ gate: null, simulator: null, matrix: [], modes: [], created_at: null }),
      ),
    });
    render(<RunPage />);
    expect(await screen.findByText("No gate decision is stored for this run.")).toBeInTheDocument();
    expect(screen.getByText("no runs")).toBeInTheDocument();
    expect(screen.getByText("unknown")).toBeInTheDocument();
    expect(screen.getByText("No cells measured yet.")).toBeInTheDocument();
    expect(screen.getByText("simulator")).toBeInTheDocument();
    expect(screen.queryByText(/Planted defect/)).toBeNull();
  });

  it("lists the cells the gate did not measure", async () => {
    visit("/run/?id=45");
    mockApi({
      "GET /api/v1/runs/45": ok(
        runDetail({
          gate: {
            decision: "pass",
            worst_flip_rate: 0,
            threshold: 0.1,
            evidence: { skipped: [{ probe: "refund-basic", perturbation: "paraphrase", reason: "no accepted variants" }] },
          },
        }),
      ),
    });
    render(<RunPage />);
    expect(await screen.findByText("Not measured: refund-basic / paraphrase: no accepted variants")).toBeInTheDocument();
  });

  it("an unknown run shows the error and nothing of a run", async () => {
    visit("/run/?id=999");
    mockApi({ "GET /api/v1/runs/999": fail(404, "run 999 not found") });
    render(<RunPage />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Not found");
    expect(alert).toHaveTextContent("run 999 not found");
    expect(screen.queryByText("Gate decision")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("Guide page", () => {
  it("is static: it makes no request, marks Guide active, explains each invariant and carries the limits", () => {
    const mock = mockApi({});
    render(<GuidePage />);
    expect(mock.calls).toHaveLength(0);
    const guide = within(screen.getByRole("navigation", { name: "Sections" })).getByRole("link", { name: "Guide" });
    expect(guide).toHaveAttribute("aria-current", "page");
    for (const name of ["Repeat run", "Irrelevance", "Order", "Format", "Monotonicity", "Paraphrase"]) {
      expect(screen.getAllByText(name).length).toBeGreaterThan(0);
    }
    expect(screen.getByTestId("limits")).toBeInTheDocument();
    expect(NAV.map((n) => n.label)).toContain("Guide");
  });
});
