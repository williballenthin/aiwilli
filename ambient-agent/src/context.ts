// Context construction: turn a consolidated drain into the payload the agent
// reviews. This is where review quality is won or lost, so it is the part most
// heavily exercised by tests.
//
// Output is both a structured `ContextPayload` (for programmatic use / the pi
// widget) and a layered `prompt` string that exploits primacy/recency: task at
// the very top, then the edit timeline, then the scope-expanded diff, then the
// task restated at the end.

import { Git } from "./git.js";
import type { ConsolidateResult, Snapshot } from "./shadow-repo.js";
import {
  detectLanguage,
  expandScope,
  sliceLines,
} from "./scope.js";
import type {
  ContextOptions,
  ContextPayload,
  ExpandedHunk,
  FileChange,
  IntentSignals,
  TimelineStep,
} from "./types.js";

/** A changed line range on the new side of a diff (1-based inclusive). */
interface NewRange {
  start: number;
  end: number;
}

/** Parse the new-side changed ranges from a unified diff body. */
export function parseNewRanges(diff: string): NewRange[] {
  const ranges: NewRange[] = [];
  const hunkRe = /^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/;
  let newLine = 0;
  let cur: NewRange | null = null;
  for (const line of diff.split("\n")) {
    const m = line.match(hunkRe);
    if (m) {
      if (cur) ranges.push(cur);
      cur = null;
      newLine = parseInt(m[1], 10);
      continue;
    }
    if (cur === null && newLine === 0) continue;
    if (line.startsWith("+") && !line.startsWith("+++")) {
      if (!cur) cur = { start: newLine, end: newLine };
      else cur.end = newLine;
      newLine++;
    } else if (line.startsWith("-") && !line.startsWith("---")) {
      // deletion: anchor a zero-width change at the current new line
      if (!cur) cur = { start: Math.max(1, newLine), end: Math.max(1, newLine) };
    } else if (line.startsWith(" ")) {
      if (cur) {
        ranges.push(cur);
        cur = null;
      }
      newLine++;
    }
  }
  if (cur) ranges.push(cur);
  return mergeRanges(ranges);
}

function mergeRanges(ranges: NewRange[]): NewRange[] {
  if (ranges.length === 0) return [];
  const sorted = [...ranges].sort((x, y) => x.start - y.start);
  const out: NewRange[] = [sorted[0]];
  for (let i = 1; i < sorted.length; i++) {
    const last = out[out.length - 1];
    if (sorted[i].start <= last.end + 1) last.end = Math.max(last.end, sorted[i].end);
    else out.push(sorted[i]);
  }
  return out;
}

/** Build the per-file net changes, scope-expanded. */
export function buildChanges(
  git: Git,
  result: ConsolidateResult,
  opts: ContextOptions,
): FileChange[] {
  const changes: FileChange[] = [];
  for (const { status, path } of git.nameStatus(result.from, result.to)) {
    const kind =
      status.startsWith("A") ? "added"
      : status.startsWith("D") ? "deleted"
      : "modified";

    const diff = git.diff(result.from, result.to, [path], { functionContext: true });

    if (kind === "deleted") {
      changes.push({ path, status: kind, diff, hunks: [] });
      continue;
    }

    const newContent = git.show(result.to, path);
    const lang = detectLanguage(path);
    // Use a tight-context diff to locate precise changed ranges.
    const tightDiff = git.diff(result.from, result.to, [path], { context: 0 });
    const ranges = parseNewRanges(tightDiff);

    const hunks: ExpandedHunk[] = [];
    const seen = new Set<string>();
    for (const r of ranges) {
      const scope = expandScope(newContent, r.start, r.end, lang, opts.maxScopeLines ?? 400);
      const key = `${scope.start}-${scope.end}`;
      if (seen.has(key)) continue; // collapse multiple edits in one scope
      seen.add(key);
      hunks.push({
        path,
        start: scope.start,
        end: scope.end,
        scope: scope.label,
        code: sliceLines(newContent, scope.start, scope.end),
      });
    }
    changes.push({ path, status: kind, diff, hunks });
  }
  return changes;
}

/** Reconstruct the edit-progression timeline from the drain's snapshots. */
export function buildTimeline(
  git: Git,
  snapshots: Snapshot[],
  opts: ContextOptions,
): TimelineStep[] {
  return snapshots.map((snap, i) => {
    const rows = git.nameStatus(snap.parent, snap.sha);
    const files = rows.map(({ path }) => {
      const d = git.diff(snap.parent, snap.sha, [path], { context: 0 });
      const ranges = parseNewRanges(d);
      return { path, ranges };
    });
    const summary = files
      .map((f) => {
        const rng = f.ranges
          .map((r) => (r.start === r.end ? `L${r.start}` : `L${r.start}-${r.end}`))
          .join(",");
        return `${f.path}${rng ? ` ${rng}` : ""}`;
      })
      .join("; ");
    const step: TimelineStep = {
      index: i + 1,
      timestamp: snap.timestamp,
      files,
      summary: summary || "(no textual change)",
    };
    if (opts.timelineDiffs) {
      step.diff = git.diff(snap.parent, snap.sha, undefined, { context: 1 });
    }
    return step;
  });
}

/** Heuristic completeness/intent signals from the post-edit state. */
export function inferIntent(git: Git, result: ConsolidateResult, changes: FileChange[]): IntentSignals {
  const reasons: string[] = [];
  let complete = true;

  for (const ch of changes) {
    if (ch.status === "deleted") continue;
    const content = git.show(result.to, ch.path);
    const lang = detectLanguage(ch.path);

    if (lang === "brace") {
      const opens = (content.match(/\{/g) || []).length;
      const closes = (content.match(/\}/g) || []).length;
      if (opens !== closes) {
        complete = false;
        reasons.push(`${ch.path}: unbalanced braces (${opens} open, ${closes} close)`);
      }
    }
    if (/\bTODO\b|\bFIXME\b|\bXXX\b/.test(content)) {
      reasons.push(`${ch.path}: contains TODO/FIXME marker`);
    }
    if (lang === "python" && /:\s*$\n(\s*)$/m.test(content)) {
      // a block header with nothing under it
      reasons.push(`${ch.path}: possible empty block body`);
    }
    if (/\b(pass|\.\.\.)\s*$/m.test(content) && lang === "python") {
      reasons.push(`${ch.path}: placeholder body (pass/...)`);
    }
  }

  // Touching a test file is a strong "ready to review" signal.
  const touchedTests = changes.some((c) => /(^|\/)(test_|.*\.test\.|.*_test\.)/.test(c.path) || /(^|\/)tests?\//.test(c.path));
  if (touchedTests) reasons.push("tests were touched");

  const posture: IntentSignals["posture"] = complete
    ? "review"
    : touchedTests
      ? "blocking-only"
      : "hold";

  return { looksComplete: complete, reasons, posture };
}

/** Render the layered prompt text (primacy/recency aware). */
export function renderPrompt(
  payload: Omit<ContextPayload, "prompt">,
  opts: ContextOptions,
): string {
  const task =
    opts.task ??
    "You are an ambient pair-editor. The human just edited the files below while you were away. Offer concise, high-signal commentary or ideas. Stay quiet about nits and work-in-progress.";

  const parts: string[] = [];
  // --- Primacy: task + posture at the very top ---
  parts.push(`# Task\n${task}`);
  parts.push(
    `# Posture\nThe edits look ${payload.intent.looksComplete ? "complete" : "in-progress"}; recommended posture: **${payload.intent.posture}**.` +
      (payload.intent.reasons.length ? `\nSignals: ${payload.intent.reasons.join("; ")}.` : ""),
  );

  // --- Edit timeline (how the human got here) ---
  if (payload.timeline.length) {
    const steps = payload.timeline
      .map((s) => `${s.index}. ${s.summary}`)
      .join("\n");
    parts.push(`# How the human got here (oldest first)\n${steps}`);
  }

  // --- The net change under review (scope-expanded) ---
  const changeBlocks: string[] = [];
  for (const ch of payload.changes) {
    const header = `## ${ch.path} (${ch.status})`;
    const body = ch.diff.trim() ? "```diff\n" + ch.diff.trimEnd() + "\n```" : "(no textual diff)";
    const scopes = ch.hunks
      .filter((h) => h.scope)
      .map((h) => `- enclosing scope: \`${h.scope}\` (L${h.start}-${h.end})`)
      .join("\n");
    changeBlocks.push([header, scopes, body].filter(Boolean).join("\n"));
  }
  parts.push(`# Net change since you last looked\n${changeBlocks.join("\n\n")}`);

  // --- Recency: restate the contract at the end ---
  parts.push(
    "# Output\nRespond with brief commentary or one concrete idea/question. If the edits look in-progress and nothing is blocking, say nothing of substance.",
  );

  return parts.join("\n\n");
}

/** Assemble the full context payload for one review cycle. */
export function buildContext(
  git: Git,
  cycle: number,
  result: ConsolidateResult,
  opts: ContextOptions = {},
): ContextPayload {
  const changes = buildChanges(git, result, opts);
  const timeline = buildTimeline(git, result.snapshots, opts);
  const intent = inferIntent(git, result, changes);
  const rawDiff = git.diff(result.from, result.to);
  const since = result.snapshots[0]?.timestamp ?? 0;
  const until = result.snapshots[result.snapshots.length - 1]?.timestamp ?? since;

  const partial: Omit<ContextPayload, "prompt"> = {
    cycle,
    since,
    until,
    changes,
    timeline,
    intent,
    rawDiff,
  };
  return { ...partial, prompt: renderPrompt(partial, opts) };
}
