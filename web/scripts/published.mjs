// Reads the published measurements from the repository's own eval files and writes them
// where the build can import them. The dashboard states limits and an operating curve;
// both come from here, so neither can be typed by hand or drift from EVAL.md.
//
//   ../EVAL.md          the limits sentence, between <!-- LIMITS --> markers
//   ../eval_report.md   the operating curve tables written by `python scripts/eval.py`
//
// A missing file or marker fails the build. A page that states a limit it could not
// read is worse than no page.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..", "..");

export function limitsSentence(evalMd) {
  const match = evalMd.match(/<!-- LIMITS -->\s*([\s\S]+?)\s*<!-- \/LIMITS -->/);
  if (!match) throw new Error("EVAL.md has no <!-- LIMITS --> block");
  return match[1].split(/\s+/).join(" ");
}

export function tableAfter(markdown, heading) {
  const start = markdown.indexOf(heading);
  if (start < 0) throw new Error(`eval_report.md has no section "${heading}"`);
  const rows = [];
  for (const line of markdown.slice(start + heading.length).split(/\r?\n/)) {
    const trimmed = line.trim();
    if (trimmed.startsWith("|")) rows.push(trimmed.slice(1, -1).split("|").map((c) => c.trim()));
    else if (rows.length) break;
  }
  if (rows.length < 3) throw new Error(`section "${heading}" has no table`);
  const [header, , ...body] = rows;
  return body.map((cells) => Object.fromEntries(header.map((name, i) => [name, cells[i]])));
}

export function falseAlarmRate(markdown) {
  const match = markdown.match(/false alarm rate: \*\*([\d.]+)\*\* \(95% CI ([\d.]+)-([\d.]+)\)/);
  if (!match) throw new Error("eval_report.md has no false alarm rate line");
  return { rate: Number(match[1]), low: Number(match[2]), high: Number(match[3]) };
}

export function published(evalMd, report) {
  return {
    limits: limitsSentence(evalMd),
    shift: tableAfter(report, "## Detection vs defect magnitude"),
    drift: tableAfter(report, "## Gradual drift"),
    flake: tableAfter(report, "## Format flake"),
    falseAlarm: falseAlarmRate(report),
    design: (report.match(/^design: (.+)$/m) ?? [])[1] ?? "",
    embedder: (report.match(/^embedder: `(.+)`$/m) ?? [])[1] ?? "",
  };
}

export function llmsTxt(data) {
  return [
    "# Seismograph",
    "",
    "> Open source statistical process control for AI systems. It runs the same question at an AI",
    "> system many times and charts how much the answers move. Apache 2.0. Free. Self hosted.",
    "",
    "## What it measures",
    "- Flip rate: share of repeated answers that differ from the usual answer.",
    "- Malformed rate: share of outputs that are not valid structured output.",
    "- Invariants: the answer must hold under repeat runs, an unrelated added sentence,",
    "  reordered sentences, changed formatting, and paraphrase. A monotonic invariant fixes the",
    "  one direction an answer may move along a ladder of inputs.",
    "- Outcome modes: distinct answers over the invariant fields, with a Wilson bound on the",
    "  share of the second one.",
    "",
    "## Published limits (verbatim from EVAL.md, measured on synthetic systems)",
    data.limits,
    "",
    "## Who decides",
    "Deterministic code computes every metric, limit and gate decision. No model issues a verdict.",
    "",
    "## Not for",
    "- Tracing, prompt playgrounds, dataset management.",
    "- Single sample answer quality as the headline number.",
    "- Causal claims from production data.",
    "",
    "## Interfaces",
    "- CLI: seismo gate --contract <yaml> --sut <package.module:attribute>",
    "- API schema: /openapi.json (every /api/v1 route needs a bearer token)",
    "- Guide: /guide/",
    "- Source: https://github.com/nuwansamaranayake/Seismograph",
    "",
  ].join("\n");
}

function main() {
  const data = published(
    readFileSync(resolve(repo, "EVAL.md"), "utf8"),
    readFileSync(resolve(repo, "eval_report.md"), "utf8"),
  );
  writeFileSync(resolve(here, "..", "lib", "published.generated.json"), JSON.stringify(data, null, 2) + "\n");
  mkdirSync(resolve(here, "..", "public"), { recursive: true });
  writeFileSync(resolve(here, "..", "public", "llms.txt"), llmsTxt(data));
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
