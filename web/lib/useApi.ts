"use client";
// One hook for every read: loading, then data or the error. Nothing else is possible,
// so no page can render numbers it did not receive.
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

export type Loaded<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; error: ApiError };

export function toApiError(cause: unknown): ApiError {
  return cause instanceof ApiError ? cause : new ApiError("server", String(cause));
}

export function useApi<T>(
  load: (() => Promise<T>) | null,
  key: string | number = "",
): { state: Loaded<T>; reload: () => void } {
  const [state, setState] = useState<Loaded<T>>({ status: "loading" });
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((n) => n + 1), []);
  const shown = useRef(key);
  useEffect(() => {
    if (!load) return;
    let live = true;
    // A reload keeps the last reading on screen until the new one arrives, so a form
    // that triggered it is not torn down mid-use. A failed reload still replaces it.
    // A different key is a different thing: its predecessor's reading is dropped at once.
    const sameThing = shown.current === key;
    shown.current = key;
    setState((previous) => (previous.status === "ready" && sameThing ? previous : { status: "loading" }));
    load().then(
      (data) => live && setState({ status: "ready", data }),
      (cause) => live && setState({ status: "error", error: toApiError(cause) }),
    );
    return () => {
      live = false;
    };
    // `load` is recreated every render by callers; `tick` and `key` drive reloads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, load === null, key]);
  return { state, reload };
}

/** Read one query parameter after mount. Static export: there is no server to read it. */
export function useQueryParam(name: string): string | null | undefined {
  const [value, setValue] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    setValue(new URLSearchParams(window.location.search).get(name));
  }, [name]);
  return value;
}
