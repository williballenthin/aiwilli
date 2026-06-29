# ambient-agent — spec (user-facing behavior)

Status: draft · Last updated: 2026-06-29

## What it is

A background engine that watches live edits to source/prose files and produces,
on demand, a consolidated review of "what changed since the agent last looked,"
with enough context for a peer agent to offer high-signal commentary unprompted.

## Inputs and outputs (the contract)

- **Input:** a stream of edit events, each `{ path, content, timestamp, range? }`
  — the full post-edit content of a file at a moment. Nothing else is required:
  no editor telemetry, cursor position, LSP state, or `atime`.
- **Output:** a `ContextPayload` per review cycle, containing:
  - `changes` — net per-file changes, each with a function/scope-expanded
    unified diff and the complete enclosing units (post-edit) touched.
  - `timeline` — the ordered edit-progression ("how the human got here"),
    reconstructed from incremental snapshots.
  - `intent` — completeness/posture heuristics (see below).
  - `prompt` — a layered, primacy/recency-aware rendering of all of the above.
  - `rawDiff` — the net unified diff for reference.

The agent never sees the git backend; it only sees the payload.

## CLI

```
ambient-agent simulate <script.json> [--json]
ambient-agent watch <paths...> [--snapshot-ms N] [--review-ms N] [--json]
```

### `simulate`

Replays a scripted edit sequence deterministically (no timers) and prints the
payload for each drain. This is the canonical way to test/inspect the engine.

Script shape:

```json
{
  "task": "optional preamble pinned top & bottom of the prompt",
  "baseline": [{ "path": "src/a.ts", "content": "...", "timestamp": 1000 }],
  "steps": [
    { "edit": { "path": "src/a.ts", "content": "...", "timestamp": 2000 } },
    { "snapshot": { "t": 2000 } },
    { "drain": { "t": 5000 } }
  ]
}
```

`edit` updates in-memory state; `snapshot` commits an incremental snapshot;
`drain` consolidates everything since the last drain and emits a payload. A
`drain` auto-snapshots any pending edits first.

### `watch`

Watches real files. Snapshots on a debounce (`--snapshot-ms`, default 1500) and
emits a review after a quiet period with no edits (`--review-ms`, default 8000).
The quiet period is the standalone stand-in for "the agent's attention returns."

## Review semantics

- **Net, not journey, is reviewed.** Many intermediate snapshots collapse into a
  single net diff. If you type `return 1` then change it to `return 2` before a
  drain, the agent sees only `return 2`. The journey is preserved in `timeline`.
- **Drains report only new work.** Each drain diffs against the previous drain
  point, so a second review never re-surfaces an earlier change.
- **Scope expansion.** Each changed region is expanded to its complete enclosing
  unit (function/class/block for code; heading section for Markdown) so the
  agent always sees a whole thing. Newly-added top-level declarations are
  labeled by the block they open.

## Intent / posture

The payload recommends a posture from the post-edit state:

- `review` — looks structurally complete; comment freely.
- `hold` — looks in-progress (e.g. unbalanced braces); stay quiet.
- `blocking-only` — in-progress but tests were touched; surface only blocking
  issues.

Signals feeding this include brace balance, `TODO`/`FIXME` markers, placeholder
bodies, and whether test files were touched.

## Not yet specified

- Prose/Markdown context beyond the edit timeline + section expansion.
- Exact "attention returns" policy inside pi (idle vs. steer eagerness).
- Surfacing of proposed *edits* (vs. commentary).
