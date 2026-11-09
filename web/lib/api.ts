// The dashboard's only door to the backend. One function per row of contracts.md.
//
// There is no fallback data here. A call that fails throws an ApiError and the page shows
// it: a board that fills itself with plausible numbers when the API is down is the
// failure this project exists to prevent.
import type {
  CalibrationResult,
  ContractDetail,
  ContractSummary,
  GoldenDetail,
  GoldenSummary,
  Judges,
  Overview,
  PanelResult,
  RegisterResult,
  Report,
  RunDetail,
  RunResult,
  Simulator,
  VariantsResult,
} from "./types";

const TOKEN_KEY = "seismograph.token";

export type ApiErrorKind = "unauthorized" | "not_found" | "invalid" | "unavailable" | "network" | "server";

export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    message: string,
    readonly status = 0,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function getToken(): string {
  return sessionStorage.getItem(TOKEN_KEY) ?? "";
}

export function setToken(token: string): void {
  if (token) sessionStorage.setItem(TOKEN_KEY, token);
  else sessionStorage.removeItem(TOKEN_KEY);
}

function kindFor(status: number): ApiErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 404) return "not_found";
  if (status === 409 || status === 422) return "invalid";
  if (status === 503) return "unavailable";
  return "server";
}

function detailOf(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI request validation: [{loc, msg}, ...]
    return detail.map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).join(".")}: ${d.msg}`).join(". ");
  }
  return `HTTP ${status}`;
}

export async function request<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (init?.body !== undefined) headers["Content-Type"] = "application/json";
  let response: Response;
  try {
    response = await fetch(path, {
      method: init?.method ?? "GET",
      headers,
      body: init?.body === undefined ? undefined : JSON.stringify(init.body),
    });
  } catch (cause) {
    throw new ApiError("network", `Could not reach the API: ${String(cause)}`);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(kindFor(response.status), detailOf(body, response.status), response.status);
  }
  return (await response.json()) as T;
}

const enc = encodeURIComponent;

export const getOverview = () => request<Overview>("/api/v1/overview");

export const listContracts = () =>
  request<{ contracts: ContractSummary[] }>("/api/v1/contracts").then((r) => r.contracts);

export const registerContract = (yaml: string) =>
  request<RegisterResult>("/api/v1/contracts", { method: "POST", body: { yaml } });

export const getContract = (name: string) => request<ContractDetail>(`/api/v1/contracts/${enc(name)}`);

export const getReport = (name: string) => request<Report>(`/api/v1/reports/${enc(name)}`);

export const launchRun = (contract: string, sut: string, t: number, seed: number) =>
  request<RunResult>("/api/v1/runs", { method: "POST", body: { contract, sut, t, seed } });

export const getRun = (id: number) => request<RunDetail>(`/api/v1/runs/${id}`);

export const listSimulators = () => request<{ suts: Simulator[] }>("/api/v1/suts").then((r) => r.suts);

export const generateVariants = (contract: string, probe: string, n: number) =>
  request<VariantsResult>("/api/v1/probes/variants", { method: "POST", body: { contract, probe, n } });

export const getJudges = () => request<Judges>("/api/v1/judges/calibration");

export const recordCalibration = (judge: string, verdicts: Record<string, string>) =>
  request<CalibrationResult>("/api/v1/judges/calibration", { method: "POST", body: { judge, verdicts } });

export const panelVerdict = (votes: Record<string, string>) =>
  request<PanelResult>("/api/v1/judges/panel", { method: "POST", body: { votes } });

export const listGolden = () => request<{ reports: GoldenSummary[] }>("/api/v1/golden").then((r) => r.reports);

export const getGolden = (contract: string) => request<GoldenDetail>(`/api/v1/golden/${enc(contract)}`);
