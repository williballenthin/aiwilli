// Core data types for the ambient editing companion engine.
//
// The engine is deliberately decoupled from any editor, filesystem watcher, or
// agent harness. Its only input is a stream of `EditEvent`s (a file's full
// content at a point in time) and its only output is a `ContextPayload` (a
// distilled diff plus supporting context). This boundary is what makes the
// engine testable in isolation and embeddable behind a thin pi wrapper.

/** A single observed edit: the full content of a file at a moment in time. */
export interface EditEvent {
  /** Repo-relative (or otherwise stable) path used as the file's key. */
  path: string;
  /** Full post-edit content of the file. */
  content: string;
  /** Milliseconds since epoch when the edit was observed. */
  timestamp: number;
  /** Optional 1-based inclusive line range the watcher believes changed. */
  range?: { start: number; end: number };
}

/** One step in the reconstructed edit-progression timeline. */
export interface TimelineStep {
  /** 1-based ordinal, oldest first. */
  index: number;
  timestamp: number;
  /** Files touched in this snapshot, with the line ranges that changed. */
  files: Array<{ path: string; ranges: Array<{ start: number; end: number }> }>;
  /** A short, human-readable summary, e.g. "edited parser.ts L40-58". */
  summary: string;
  /** Small per-step diff, included when it adds signal. */
  diff?: string;
}

/** The complete enclosing syntactic unit around a change, post-edit. */
export interface ExpandedHunk {
  path: string;
  /** 1-based inclusive line range of the enclosing scope in the post-edit file. */
  start: number;
  end: number;
  /** Label of the enclosing scope, e.g. "function parse" or "## Heading". */
  scope?: string;
  /** The post-edit source of the complete enclosing unit. */
  code: string;
}

/** Per-file net change summary across the consolidated drain. */
export interface FileChange {
  path: string;
  status: "added" | "modified" | "deleted";
  /** Unified diff for the file, expanded to function/scope context. */
  diff: string;
  /** Complete enclosing units for each changed region (post-edit). */
  hunks: ExpandedHunk[];
}

/**
 * The complete payload handed to the agent for one review cycle. The agent
 * never sees the git backend; it sees this structured object (and `prompt`,
 * the rendered text form).
 */
export interface ContextPayload {
  /** Monotonic id of this review cycle. */
  cycle: number;
  /** Window of wall-clock time this drain covers. */
  since: number;
  until: number;
  /** Net per-file changes, scope-expanded. */
  changes: FileChange[];
  /** Reconstructed edit-progression timeline (oldest first). */
  timeline: TimelineStep[];
  /** Heuristic completeness/intent signals (see context builder). */
  intent: IntentSignals;
  /** The fully rendered, layered prompt text (primacy/recency aware). */
  prompt: string;
  /** Net unified diff across the whole drain (unexpanded), for reference. */
  rawDiff: string;
}

/** Heuristic signals about whether the work looks finished or in-progress. */
export interface IntentSignals {
  /** True when post-edit files parse/scan as structurally complete. */
  looksComplete: boolean;
  /** Reasons feeding the completeness verdict. */
  reasons: string[];
  /** Recommended posture for the agent. */
  posture: "review" | "hold" | "blocking-only";
}

/** Options controlling context construction. */
export interface ContextOptions {
  /** Max lines of surrounding scope to include per hunk (safety cap). */
  maxScopeLines?: number;
  /** Whether to include per-step diffs in the timeline. */
  timelineDiffs?: boolean;
  /** A short task/preamble pinned to the top and bottom of the prompt. */
  task?: string;
}
