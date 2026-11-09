import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ContractEditor, TEMPLATE } from "@/components/ContractEditor";
import { RunLauncher } from "@/components/RunLauncher";
import { fail, mockApi, ok } from "./helpers";
import { runResult, simulators } from "./fixtures";

const SUTS = "GET /api/v1/suts";
const RUNS = "POST /api/v1/runs";

async function ready() {
  await screen.findByLabelText("System under test");
}

describe("RunLauncher", () => {
  it("lists the simulators and tags the chosen one as a simulator, with its planted defect", async () => {
    mockApi({ [SUTS]: ok({ suts: simulators() }) });
    render(<RunLauncher contract="c" nextT={0} onDone={() => {}} />);
    await ready();
    expect(screen.getByLabelText("System under test")).toHaveValue("stable");
    expect(screen.getByText("simulator")).toBeInTheDocument();
    expect(screen.getByText(/No planted defect\./)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("System under test"), "drifting");
    expect(screen.getByText(/Planted defect: decision flips from t = 4\./)).toBeInTheDocument();
  });

  it("defaults to the system the contract was last run against", async () => {
    mockApi({ [SUTS]: ok({ suts: simulators() }) });
    render(<RunLauncher contract="c" nextT={3} lastSut="drifting" onDone={() => {}} />);
    await ready();
    expect(screen.getByLabelText("System under test")).toHaveValue("drifting");
  });

  it("shows no description when the default system is not in the catalog", async () => {
    mockApi({ [SUTS]: ok({ suts: simulators() }) });
    render(<RunLauncher contract="c" nextT={0} lastSut="retired" onDone={() => {}} />);
    await ready();
    expect(screen.queryByText("simulator")).toBeNull();
  });

  it("launches count runs one after another at t = nextT, nextT + 1, ... and then calls onDone", async () => {
    const order: number[] = [];
    const mock = mockApi({
      [SUTS]: ok({ suts: simulators() }),
      [RUNS]: (call) => {
        order.push((call.body as { t: number }).t);
        return ok(runResult({ run_id: 40 + order.length }));
      },
    });
    const onDone = vi.fn();
    render(<RunLauncher contract="refund-agent" nextT={5} onDone={onDone} />);
    await ready();
    await userEvent.selectOptions(screen.getByLabelText("Runs"), "4");
    await userEvent.clear(screen.getByLabelText("Seed"));
    await userEvent.type(screen.getByLabelText("Seed"), "9");
    await userEvent.click(screen.getByRole("button", { name: "Run from t = 5" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledOnce());
    expect(order).toEqual([5, 6, 7, 8]);
    expect(mock.to(RUNS)[0]?.body).toEqual({ contract: "refund-agent", sut: "stable", t: 5, seed: 9 });
    expect(screen.getByTestId("last-run")).toHaveTextContent("run 44");
    expect(screen.getByRole("button", { name: /Run from t = 5/ })).toBeEnabled();
  });

  it("disables the button and shows progress while runs are in flight", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve));
    const fetchMock = vi.fn(async (path: unknown) => {
      if (String(path) === SUTS.slice(4)) return { ok: true, status: 200, json: async () => ({ suts: simulators() }) };
      await gate;
      return { ok: true, status: 200, json: async () => runResult() };
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<RunLauncher contract="c" nextT={0} onDone={() => {}} />);
    await ready();
    await userEvent.selectOptions(screen.getByLabelText("Runs"), "4");
    await userEvent.click(screen.getByRole("button", { name: "Run from t = 0" }));
    const busy = await screen.findByRole("button", { name: "run 1 of 4" });
    expect(busy).toBeDisabled();
    release();
    await screen.findByRole("button", { name: "Run from t = 0" });
  });

  it("shows the last result with gate badge, reasons, worst cell and skipped count", async () => {
    mockApi({
      [SUTS]: ok({ suts: simulators() }),
      [RUNS]: ok(
        runResult({
          gate: "block",
          worst_flip_rate: 0.3,
          reasons: ["flip rate 30.0% over 10.0%", "malformed over tolerance"],
          worst_cell: { probe: "refund-basic", perturbation: "reordering", field: "decision" },
          skipped: [
            { probe: "p", perturbation: "paraphrase", reason: "no accepted variants" },
            { probe: "q", perturbation: "paraphrase", reason: "no accepted variants" },
          ],
        }),
      ),
    });
    render(<RunLauncher contract="c" nextT={0} onDone={() => {}} />);
    await ready();
    await userEvent.click(screen.getByRole("button", { name: /Run from/ }));
    const last = await screen.findByTestId("last-run");
    expect(last).toHaveTextContent("block");
    expect(last).toHaveTextContent("30.0%");
    expect(last).toHaveTextContent("tolerance of 10.0%");
    expect(last).toHaveTextContent("Worst cell: refund-basic under reordering.");
    expect(last).toHaveTextContent("flip rate 30.0% over 10.0%");
    expect(last).toHaveTextContent("malformed over tolerance");
    expect(last).toHaveTextContent("2 cells not measured: no accepted variants.");
  });

  it("uses the singular for one skipped cell and says nothing when nothing was skipped", async () => {
    mockApi({
      [SUTS]: ok({ suts: simulators() }),
      [RUNS]: [ok(runResult({ skipped: [{ probe: "p", perturbation: "x", reason: "r" }] })), ok(runResult())],
    });
    render(<RunLauncher contract="c" nextT={0} onDone={() => {}} />);
    await ready();
    await userEvent.click(screen.getByRole("button", { name: /Run from/ }));
    expect(await screen.findByTestId("last-run")).toHaveTextContent("1 cell not measured: r.");
    await userEvent.click(screen.getByRole("button", { name: /Run from/ }));
    await waitFor(() => expect(screen.getByTestId("last-run")).not.toHaveTextContent("not measured"));
  });

  it("shows the API error message on failure, keeps no result, and still calls onDone", async () => {
    mockApi({ [SUTS]: ok({ suts: simulators() }), [RUNS]: fail(409, "contract has no plan") });
    const onDone = vi.fn();
    render(<RunLauncher contract="c" nextT={0} onDone={onDone} />);
    await ready();
    await userEvent.click(screen.getByRole("button", { name: /Run from/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("contract has no plan");
    expect(screen.queryByTestId("last-run")).toBeNull();
    expect(onDone).toHaveBeenCalledOnce();
  });

  it("shows the error panel, not a launcher, when the simulator catalog cannot be read", async () => {
    mockApi({ [SUTS]: fail(500, "catalog down") });
    render(<RunLauncher contract="c" nextT={0} onDone={() => {}} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("catalog down");
    expect(screen.queryByRole("button", { name: /Run from/ })).toBeNull();
  });
});

describe("ContractEditor", () => {
  it("starts from the template and posts whatever YAML is in the box", async () => {
    const mock = mockApi({ "POST /api/v1/contracts": ok({ contract: "my-refund-contract", plan_id: "plan-9", entries: 12 }) });
    const onRegistered = vi.fn();
    render(<ContractEditor onRegistered={onRegistered} />);
    const box = screen.getByLabelText("Contract YAML");
    expect(box).toHaveValue(TEMPLATE);
    await userEvent.click(screen.getByRole("button", { name: "Register and compile" }));
    expect(await screen.findByText(/Registered/)).toBeInTheDocument();
    expect(mock.calls[0]?.body).toEqual({ yaml: TEMPLATE });
    expect(screen.getByRole("link", { name: "my-refund-contract" })).toHaveAttribute("href", "/contract/?name=my-refund-contract");
    expect(screen.getByText("plan-9")).toBeInTheDocument();
    expect(screen.getByText(/12 cells/)).toBeInTheDocument();
    expect(onRegistered).toHaveBeenCalledOnce();
  });

  it("sends edited text and disables registering an empty box", async () => {
    const mock = mockApi({ "POST /api/v1/contracts": ok({ contract: "c", plan_id: "p", entries: 1 }) });
    render(<ContractEditor onRegistered={() => {}} />);
    const box = screen.getByLabelText("Contract YAML");
    await userEvent.clear(box);
    expect(screen.getByRole("button", { name: "Register and compile" })).toBeDisabled();
    await userEvent.type(box, "contract: x");
    await userEvent.click(screen.getByRole("button", { name: "Register and compile" }));
    await screen.findByRole("link", { name: "c" });
    expect(mock.calls[0]?.body).toEqual({ yaml: "contract: x" });
  });

  it("shows the 422 detail message, no success line, and does not call onRegistered", async () => {
    mockApi({ "POST /api/v1/contracts": fail(422, "invariant field is missing") });
    const onRegistered = vi.fn();
    render(<ContractEditor onRegistered={onRegistered} />);
    await userEvent.click(screen.getByRole("button", { name: "Register and compile" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("invariant field is missing");
    expect(screen.queryByText(/Registered/)).toBeNull();
    expect(onRegistered).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Register and compile" })).toBeEnabled();
  });
});
