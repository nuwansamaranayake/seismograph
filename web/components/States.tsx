"use client";
import { type FormEvent, type ReactNode, useState } from "react";
import { type ApiError, setToken } from "@/lib/api";
import type { Loaded } from "@/lib/useApi";

export function Loading({ what }: { what: string }) {
  return (
    <p className="dim mono" role="status">
      Reading {what}…
    </p>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="card">
      <span className="label">Nothing recorded</span>
      <h3>{title}</h3>
      <div className="dim">{children}</div>
    </div>
  );
}

/** The API refused the request for lack of a token. Ask for one. Never show an empty board. */
export function Connect({ onConnected }: { onConnected: () => void }) {
  const [value, setValue] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setToken(value.trim());
    onConnected();
  };
  return (
    <form className="card note" onSubmit={submit}>
      <span className="label">Locked</span>
      <h3>This instance needs its API token</h3>
      <p className="dim">
        Every reading on this board comes from the API, and this API requires a bearer token. Paste the token your
        operator set as <code>SMOKE_TEST_TOKEN</code>. It is kept in this browser tab only and is cleared when the tab
        closes.
      </p>
      <div className="form-row">
        <label className="field">
          <span className="label">API token</span>
          <input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            autoComplete="off"
            aria-label="API token"
          />
        </label>
        <button type="submit" disabled={!value.trim()}>
          Connect
        </button>
      </div>
    </form>
  );
}

const HEADLINE: Record<ApiError["kind"], string> = {
  unauthorized: "The API refused the token",
  not_found: "Not found",
  invalid: "The API rejected the request",
  unavailable: "Not available on this instance",
  network: "The API could not be reached",
  server: "The API returned an error",
};

export function ErrorPanel({ error, onRetry }: { error: ApiError; onRetry: () => void }) {
  if (error.kind === "unauthorized") return <Connect onConnected={onRetry} />;
  return (
    <div className="card alarm" role="alert">
      <span className="label">No reading</span>
      <h3>{HEADLINE[error.kind]}</h3>
      <p>{error.message}</p>
      <p className="dim">Nothing is shown in its place. The board does not fill in numbers it did not receive.</p>
      <button type="button" className="secondary" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}

/** Render `children` with the data once it is there. Until then: the wait, or the error. */
export function Data<T>({
  state,
  reload,
  what,
  children,
}: {
  state: Loaded<T>;
  reload: () => void;
  what: string;
  children: (data: T) => ReactNode;
}) {
  if (state.status === "loading") return <Loading what={what} />;
  if (state.status === "error") return <ErrorPanel error={state.error} onRetry={reload} />;
  return <>{children(state.data)}</>;
}
