# ambient-agent

An **ambient editing companion**: a background engine that watches your live
edits, consolidates the keystroke-level churn into one meaningful net change,
builds rich review context around it, and hands that to an agent — so a peer can
comment on what you're doing *as you do it*, without being prompted.

This package is the **standalone engine** plus a **minimal pi wrapper**. All the
substantive logic (events, shadow-git diffing, context construction) lives in
`src/` and is exercised without any editor or agent harness. The pi extension
(`pi/ambient-agent.ts`) is a thin adapter.

See `docs/spec.md` for behavior and `docs/design.md` for the architecture and
the relationship to the original design vision.

## Why a standalone core

The engine's only input is a stream of `EditEvent`s (a file's full content at a
point in time) and its only output is a `ContextPayload` (a distilled diff plus
supporting context). That boundary is what makes it testable in isolation and
embeddable behind a thin wrapper. The git shadow repo, the two-tier
branch/merge history, the `last-reviewed` pointer — none of it leaks to the
agent.

## How to test it (the fast path)

Replay a scripted edit sequence deterministically — no editor, no watcher, no
agent — and print the context the agent would receive for each review:

```bash
bun run src/cli.ts simulate examples/parser-session.json
```

Add `--json` to see the full structured payload (changes, scopes, timeline,
intent signals).

The automated suite drives the same path with synthetic events and asserts on
the diffs, scope expansion, timeline reconstruction, and intent:

```bash
bun test
bun run typecheck
```

## How to use it on real files

Watch files in your editor of choice; a review prints after a quiet period:

```bash
bun run src/cli.ts watch src/parser.ts src/lexer.ts --review-ms 8000
```

Edit a watched file, pause, and the consolidated net diff + context prints to
stdout. The shadow repo lives in a temp dir and is removed on exit.

## pi integration

`pi/ambient-agent.ts` wires the engine into pi: it starts the watcher in
`session_start`, drives the review drain from pi's idle signal (the "agent
attention returns" boundary), injects the context as a turn via
`pi.sendMessage`, and renders commentary in a side widget. It reuses the
standalone `AmbientRunner` verbatim with `autoReview: false`.

## Requirements

- [Bun](https://bun.sh) (dev runtime + test runner) and `git`.
- The engine itself uses only Node stdlib + the `git` CLI, so it also runs under
  Node ≥ 20.
