import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import * as api from "@/lib/api";
import { ApiError, getToken, request, setToken } from "@/lib/api";
import {
  metricText,
  num,
  parseMap,
  pct,
  PERTURBATION_LABEL,
  perturbationLabel,
  signatureText,
  when,
} from "@/lib/format";
import { toApiError, useApi, useQueryParam } from "@/lib/useApi";
import { fail, mockApi, ok, visit } from "./helpers";

describe("token storage", () => {
  it("is empty until set, then kept in sessionStorage and cleared by an empty value", () => {
    expect(getToken()).toBe("");
    setToken("abc");
    expect(sessionStorage.getItem("seismograph.token")).toBe("abc");
    expect(getToken()).toBe("abc");
    setToken("");
    expect(getToken()).toBe("");
  });
});

describe("request", () => {
  it("sends no Authorization header when there is no token", async () => {
    const mock = mockApi({ "GET /x": ok({ a: 1 }) });
    await expect(request("/x")).resolves.toEqual({ a: 1 });
    expect(mock.calls[0]?.authorization).toBeUndefined();
  });

  it("sends the stored token as a Bearer header and posts JSON bodies", async () => {
    setToken("secret");
    const mock = mockApi({ "POST /x": ok({}) });
    await request("/x", { method: "POST", body: { k: "v" } });
    expect(mock.calls[0]).toMatchObject({ authorization: "Bearer secret", body: { k: "v" } });
    const init = mock.fn.mock.calls[0]?.[1] as { headers: Record<string, string> };
    expect(init.headers["Content-Type"]).toBe("application/json");
  });

  it.each([
    [401, "unauthorized"],
    [404, "not_found"],
    [409, "invalid"],
    [422, "invalid"],
    [503, "unavailable"],
    [500, "server"],
    [418, "server"],
  ])("maps HTTP %i to the %s kind", async (status, kind) => {
    mockApi({ "GET /x": fail(status, "boom") });
    const error = await request("/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ kind, status, message: "boom" });
  });

  it("turns a rejected fetch into a network error that names the cause", async () => {
    mockApi({ "GET /x": { throws: new Error("offline") } });
    await expect(request("/x")).rejects.toMatchObject({ kind: "network", message: expect.stringContaining("offline") });
  });

  it("joins FastAPI validation entries into one message", async () => {
    mockApi({
      "POST /x": fail(422, [
        { loc: ["body", "yaml"], msg: "field required" },
        { msg: "bad" },
      ]),
    });
    await expect(request("/x", { method: "POST", body: {} })).rejects.toMatchObject({
      message: "body.yaml: field required. : bad",
    });
  });

  it("falls back to the status when the error body has no usable detail or is not JSON", async () => {
    mockApi({ "GET /a": { status: 500, body: { other: 1 } }, "GET /b": { status: 502, unparsable: true } });
    await expect(request("/a")).rejects.toMatchObject({ message: "HTTP 500" });
    await expect(request("/b")).rejects.toMatchObject({ message: "HTTP 502" });
  });
});

describe("typed endpoints", () => {
  it("call the documented paths, encode names and unwrap list envelopes", async () => {
    const mock = mockApi({
      "GET /api/v1/overview": ok({ contracts: 0 }),
      "GET /api/v1/contracts": ok({ contracts: [{ name: "a" }] }),
      "POST /api/v1/contracts": ok({ contract: "a" }),
      "GET /api/v1/contracts/a%20b": ok({ name: "a b" }),
      "GET /api/v1/reports/a%20b": ok({ contract: "a b" }),
      "POST /api/v1/runs": ok({ run_id: 1 }),
      "GET /api/v1/runs/5": ok({ run_id: 5 }),
      "GET /api/v1/suts": ok({ suts: [{ name: "stable" }] }),
      "POST /api/v1/probes/variants": ok({ accepted: 1 }),
      "GET /api/v1/judges/calibration": ok({ judges: [] }),
      "POST /api/v1/judges/calibration": ok({ round: 1 }),
      "POST /api/v1/judges/panel": ok({ label: null }),
      "GET /api/v1/golden": ok({ reports: [{ contract: "g" }] }),
      "GET /api/v1/golden/g%2Fh": ok({ contract: "g/h" }),
    });
    await api.getOverview();
    await expect(api.listContracts()).resolves.toEqual([{ name: "a" }]);
    await api.registerContract("yaml: 1");
    await api.getContract("a b");
    await api.getReport("a b");
    await api.launchRun("c", "stable", 3, 7);
    await api.getRun(5);
    await expect(api.listSimulators()).resolves.toEqual([{ name: "stable" }]);
    await api.generateVariants("c", "p", 5);
    await api.getJudges();
    await api.recordCalibration("j", { a1: "clean" });
    await api.panelVerdict({ j: "clean" });
    await expect(api.listGolden()).resolves.toEqual([{ contract: "g" }]);
    await api.getGolden("g/h");
    expect(mock.calls).toHaveLength(14);
    expect(mock.to("POST /api/v1/contracts")[0]?.body).toEqual({ yaml: "yaml: 1" });
    expect(mock.to("POST /api/v1/runs")[0]?.body).toEqual({ contract: "c", sut: "stable", t: 3, seed: 7 });
    expect(mock.to("POST /api/v1/probes/variants")[0]?.body).toEqual({ contract: "c", probe: "p", n: 5 });
    expect(mock.to("POST /api/v1/judges/calibration")[0]?.body).toEqual({ judge: "j", verdicts: { a1: "clean" } });
    expect(mock.to("POST /api/v1/judges/panel")[0]?.body).toEqual({ votes: { j: "clean" } });
  });
});

describe("toApiError", () => {
  it("keeps an ApiError and wraps anything else as a server error", () => {
    const original = new ApiError("invalid", "no", 422);
    expect(toApiError(original)).toBe(original);
    expect(toApiError("odd")).toMatchObject({ kind: "server", message: "odd" });
  });
});

describe("useApi", () => {
  it("goes from loading to ready", async () => {
    const { result } = renderHook(() => useApi(() => Promise.resolve(5)));
    expect(result.current.state.status).toBe("loading");
    await waitFor(() => expect(result.current.state).toEqual({ status: "ready", data: 5 }));
  });

  it("reports a rejection as an error state, wrapping non-ApiErrors", async () => {
    const { result } = renderHook(() => useApi(() => Promise.reject(new Error("x"))));
    await waitFor(() => expect(result.current.state.status).toBe("error"));
    expect(result.current.state).toMatchObject({ error: { kind: "server" } });
  });

  it("never loads while the loader is null", async () => {
    const { result } = renderHook(() => useApi<number>(null));
    await act(async () => {});
    expect(result.current.state.status).toBe("loading");
  });

  it("keeps the previous data on screen during a reload, then swaps it", async () => {
    let n = 0;
    let release: (v: number) => void = () => {};
    const { result } = renderHook(() =>
      useApi(() => {
        n += 1;
        if (n === 1) return Promise.resolve(1);
        return new Promise<number>((resolve) => {
          release = resolve;
        });
      }, "k"),
    );
    await waitFor(() => expect(result.current.state).toEqual({ status: "ready", data: 1 }));
    act(() => result.current.reload());
    expect(result.current.state).toEqual({ status: "ready", data: 1 });
    await act(async () => release(2));
    expect(result.current.state).toEqual({ status: "ready", data: 2 });
  });

  it("drops the old data at once when the key changes", async () => {
    const never = new Promise<string>(() => {});
    const { result, rerender } = renderHook(({ k }: { k: string }) => useApi(() => (k === "a" ? Promise.resolve("A") : never), k), {
      initialProps: { k: "a" },
    });
    await waitFor(() => expect(result.current.state).toEqual({ status: "ready", data: "A" }));
    rerender({ k: "b" });
    expect(result.current.state.status).toBe("loading");
  });

  it("ignores an answer that arrives after unmount", async () => {
    let resolve: (v: number) => void = () => {};
    const { result, unmount } = renderHook(() => useApi(() => new Promise<number>((r) => (resolve = r))));
    unmount();
    await act(async () => resolve(1));
    expect(result.current.state.status).toBe("loading");
  });

  it("a failed reload replaces the data with the error", async () => {
    let n = 0;
    const { result } = renderHook(() =>
      useApi(() => (++n === 1 ? Promise.resolve(1) : Promise.reject(new ApiError("unavailable", "down", 503))), "k"),
    );
    await waitFor(() => expect(result.current.state.status).toBe("ready"));
    act(() => result.current.reload());
    await waitFor(() => expect(result.current.state.status).toBe("error"));
  });
});

describe("useQueryParam", () => {
  it("is undefined before mount reads the address, then the value or null", async () => {
    visit("/contract/?name=refund-agent");
    const { result } = renderHook(() => useQueryParam("name"));
    await waitFor(() => expect(result.current).toBe("refund-agent"));
    const { result: absent } = renderHook(() => useQueryParam("missing"));
    await waitFor(() => expect(absent.current).toBeNull());
  });
});

describe("format", () => {
  it("writes rates as percentages and numbers with fixed digits", () => {
    expect(pct(0.035)).toBe("3.5%");
    expect(pct(0.5, 0)).toBe("50%");
    expect(num(1.23456)).toBe("1.235");
    expect(num(1.5, 1)).toBe("1.5");
  });

  it("writes timestamps in UTC and says unknown for missing or bad ones", () => {
    expect(when("2026-11-01T10:05:59Z")).toBe("2026-11-01 10:05Z");
    expect(when(null)).toBe("unknown");
    expect(when("not a date")).toBe("unknown");
  });

  it("writes a signature as field = value pairs, lists in brackets, empty as malformed", () => {
    expect(signatureText({ decision: "yes", ids: ["a", "b"] })).toBe("decision = yes · ids = [a, b]");
    expect(signatureText({})).toBe("malformed output");
  });

  it("labels perturbations and passes unknown ones through", () => {
    expect(perturbationLabel("irrelevant_context")).toBe("Irrelevance");
    expect(perturbationLabel("mystery")).toBe("mystery");
    expect(Object.keys(PERTURBATION_LABEL)).toContain("monotonic");
  });

  it("parseMap accepts a map of strings", () => {
    expect(parseMap('{"a": "x"}')).toEqual({ a: "x" });
  });

  it.each([
    ["{nope", "That is not valid JSON."],
    ["[1]", "Expected a JSON object."],
    ["null", "Expected a JSON object."],
    ["3", "Expected a JSON object."],
    ["{}", "The object is empty."],
    ['{"a": 1}', "Every value must be a label in quotes."],
  ])("parseMap rejects %s with its own message", (text, message) => {
    expect(parseMap(text)).toBe(message);
  });

  it("metricText shows rates as percentages, counts as counts, nesting readably", () => {
    expect(metricText("recall", 0.95)).toBe("95.0%");
    expect(metricText("false_positive_rate", 0.02)).toBe("2.0%");
    expect(metricText("recall", 3)).toBe("3");
    expect(metricText("items_total", 30)).toBe("30");
    expect(metricText("note", "text")).toBe("text");
    expect(metricText("label_counts", { clean_items: 20, planted: 10 })).toBe("clean items 20 · planted 10");
    expect(metricText("x", [1, 2])).toBe("[1,2]");
    expect(metricText("x", null)).toBe("null");
  });
});
