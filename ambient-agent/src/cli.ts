#!/usr/bin/env bun
// Standalone CLI for the ambient editing companion engine.
//
//   ambient-agent simulate <script.json> [--json]
//       Replay a scripted edit sequence deterministically (no timers) and print
//       the context payload for each drain. This is the primary test/demo
//       vehicle: it exercises events -> diffs -> context with no editor, no
//       filesystem watcher, and no agent harness.
//
//   ambient-agent watch <paths...> [--snapshot-ms N] [--review-ms N] [--json]
//       Watch real files, snapshot on a debounce, and emit a review on a quiet
//       period. Lets you see the engine working in your own editor without pi.

import { readFileSync } from "node:fs";
import { AmbientSession } from "./session.js";
import { AmbientRunner } from "./watcher.js";
import type { ContextPayload, EditEvent } from "./types.js";

interface SimStep {
  edit?: EditEvent;
  snapshot?: { t: number };
  drain?: { t: number };
}
interface SimScript {
  task?: string;
  baseline: EditEvent[];
  steps: SimStep[];
}

function printPayload(p: ContextPayload, asJson: boolean): void {
  if (asJson) {
    process.stdout.write(JSON.stringify(p, null, 2) + "\n");
    return;
  }
  const bar = "=".repeat(72);
  process.stdout.write(`\n${bar}\n REVIEW CYCLE ${p.cycle}\n${bar}\n`);
  process.stdout.write(p.prompt + "\n");
}

function runSimulate(file: string, asJson: boolean): void {
  const script: SimScript = JSON.parse(readFileSync(file, "utf8"));
  const session = new AmbientSession({ task: script.task, timelineDiffs: true });
  try {
    session.start(script.baseline);
    for (const step of script.steps) {
      if (step.edit) session.recordEdit(step.edit);
      if (step.snapshot) session.snapshot(step.snapshot.t);
      if (step.drain) {
        const payload = session.drain(step.drain.t);
        if (payload) printPayload(payload, asJson);
        else process.stdout.write("\n(drain: nothing new to review)\n");
      }
    }
  } finally {
    session.dispose();
  }
}

function runWatch(paths: string[], opts: { snapshotMs?: number; reviewMs?: number; json: boolean }): void {
  const runner = new AmbientRunner(paths, {
    timelineDiffs: true,
    snapshotDebounceMs: opts.snapshotMs,
    reviewQuietMs: opts.reviewMs,
    onReview: (p) => printPayload(p, opts.json),
  });
  runner.start();
  process.stderr.write(
    `watching ${paths.length} file(s); shadow repo at ${runner.shadowDir}\n` +
      `edit a file, then pause; a review prints after the quiet period.\n` +
      `Ctrl-C to stop.\n`,
  );
  const stop = () => {
    runner.dispose();
    process.exit(0);
  };
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);
}

function parseFlags(args: string[]): { positional: string[]; flags: Map<string, string | boolean> } {
  const positional: string[] = [];
  const flags = new Map<string, string | boolean>();
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a.startsWith("--")) {
      const key = a.slice(2);
      const next = args[i + 1];
      if (next !== undefined && !next.startsWith("--")) {
        flags.set(key, next);
        i++;
      } else {
        flags.set(key, true);
      }
    } else {
      positional.push(a);
    }
  }
  return { positional, flags };
}

function main(): void {
  const [cmd, ...rest] = process.argv.slice(2);
  const { positional, flags } = parseFlags(rest);
  const asJson = flags.get("json") === true;

  switch (cmd) {
    case "simulate": {
      if (!positional[0]) {
        process.stderr.write("usage: ambient-agent simulate <script.json> [--json]\n");
        process.exit(2);
      }
      runSimulate(positional[0], asJson);
      break;
    }
    case "watch": {
      if (positional.length === 0) {
        process.stderr.write("usage: ambient-agent watch <paths...> [--snapshot-ms N] [--review-ms N] [--json]\n");
        process.exit(2);
      }
      runWatch(positional, {
        snapshotMs: flags.has("snapshot-ms") ? Number(flags.get("snapshot-ms")) : undefined,
        reviewMs: flags.has("review-ms") ? Number(flags.get("review-ms")) : undefined,
        json: asJson,
      });
      break;
    }
    default:
      process.stderr.write(
        "ambient-agent — ambient editing companion engine\n\n" +
          "commands:\n" +
          "  simulate <script.json> [--json]   replay a scripted edit sequence\n" +
          "  watch <paths...> [--json]         watch real files and print reviews\n",
      );
      process.exit(cmd ? 2 : 0);
  }
}

main();
