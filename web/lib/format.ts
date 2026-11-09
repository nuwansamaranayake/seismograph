// How numbers are written on screen. Rates are percentages with one decimal, because a
// flip rate of 0.035 and one of 0.35 must not be confusable at a glance.

export function pct(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function num(value: number, digits = 3): string {
  return value.toFixed(digits);
}

export function when(iso: string | null): string {
  if (!iso) return "unknown";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "unknown";
  return date.toISOString().replace("T", " ").slice(0, 16) + "Z";
}

export function signatureText(signature: Record<string, unknown>): string {
  const parts = Object.entries(signature).map(
    ([field, value]) => `${field} = ${Array.isArray(value) ? `[${value.join(", ")}]` : String(value)}`,
  );
  return parts.length ? parts.join(" · ") : "malformed output";
}

export const PERTURBATION_LABEL: Record<string, string> = {
  repeat_run: "Repeat run",
  paraphrase: "Paraphrase",
  irrelevant_context: "Irrelevance",
  reordering: "Order",
  format: "Format",
  monotonic: "Monotonicity",
};

export function perturbationLabel(name: string): string {
  return PERTURBATION_LABEL[name] ?? name;
}

export const QUARANTINE_LABEL: Record<string, string> = {
  below_floor: "below the agreement floor",
  drift: "drifted from its own baseline",
  uncalibrated: "never calibrated",
  active: "active",
};

/** Why a judge's vote is not counted, in words. A missing reason says so instead of "null". */
export function quarantineText(reason: string | null): string {
  if (reason === null) return "no reason recorded";
  return QUARANTINE_LABEL[reason] ?? reason;
}

/** Parse `{"id": "label", ...}`. Returns the map, or the reason it is not one. */
export function parseMap(text: string): Record<string, string> | string {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return "That is not valid JSON.";
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) return "Expected a JSON object.";
  const entries = Object.entries(value);
  if (!entries.length) return "The object is empty.";
  if (entries.some(([, v]) => typeof v !== "string")) return "Every value must be a label in quotes.";
  return value as Record<string, string>;
}

/** A metric value as text: rates as percentages, counts as they are, objects as JSON. */
export function metricText(key: string, value: unknown): string {
  if (typeof value === "number") {
    const isRate = /rate|recall|accuracy|cutoff/.test(key) && value <= 1;
    return isRate ? pct(value) : String(value);
  }
  if (typeof value === "string") return value;
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    // One level of nesting, as "name value" pairs: readable in a table cell.
    return Object.entries(value)
      .map(([name, inner]) => `${name.replaceAll("_", " ")} ${metricText(key, inner)}`)
      .join(" · ");
  }
  return JSON.stringify(value);
}
