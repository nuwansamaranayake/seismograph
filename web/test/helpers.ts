import { vi } from "vitest";

export interface Call {
  method: string;
  path: string;
  body: unknown;
  authorization: string | undefined;
}

export interface Reply {
  status?: number;
  body?: unknown;
  /** FastAPI style `detail` for an error answer. */
  detail?: unknown;
  /** The answer is not JSON at all. */
  unparsable?: boolean;
  /** fetch itself rejects, as when the API is down. */
  throws?: unknown;
}

export type Route = Reply | ((call: Call) => Reply);

/** An error answer. */
export const fail = (status: number, detail?: unknown): Reply => ({ status, detail });
/** A good answer. */
export const ok = (body: unknown): Reply => ({ status: 200, body });

interface FakeInit {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
}

function answer(reply: Reply) {
  const status = reply.status ?? 200;
  const body = reply.body ?? (reply.detail !== undefined ? { detail: reply.detail } : {});
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => (reply.unparsable ? Promise.reject(new SyntaxError("Unexpected token")) : Promise.resolve(body)),
  };
}

/**
 * Stub fetch. Routes are keyed "METHOD path". A list of routes answers in order and then
 * repeats its last entry. An unmatched request answers 404 and is recorded in `calls`.
 */
export function mockApi(routes: Record<string, Route | Route[]>) {
  const calls: Call[] = [];
  const used: Record<string, number> = {};
  const fn = vi.fn(async (input: unknown, init?: FakeInit) => {
    const method = init?.method ?? "GET";
    const path = String(input);
    calls.push({
      method,
      path,
      body: init?.body === undefined ? undefined : (JSON.parse(init.body) as unknown),
      authorization: init?.headers?.Authorization,
    });
    const call = calls[calls.length - 1] as Call;
    const key = `${method} ${path}`;
    const entry = routes[key];
    if (entry === undefined) return answer({ status: 404, detail: `unmocked ${key}` });
    const index = (used[key] = (used[key] ?? -1) + 1);
    const route = Array.isArray(entry) ? (entry[Math.min(index, entry.length - 1)] as Route) : entry;
    const reply = typeof route === "function" ? route(call) : route;
    if (reply.throws !== undefined) throw reply.throws;
    return answer(reply);
  });
  vi.stubGlobal("fetch", fn);
  return {
    calls,
    fn,
    /** Requests made to "METHOD path". */
    to: (key: string) => calls.filter((c) => `${c.method} ${c.path}` === key),
  };
}

/** Set the address bar the way the static export would have it. */
export function visit(path: string): void {
  window.history.pushState({}, "", path);
}
