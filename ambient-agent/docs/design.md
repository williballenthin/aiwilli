# ambient-agent — design (implementation)

Status: draft · Last updated: 2026-06-29

This document records the implemented architecture. The broader product vision
(why ambient editing, the landscape survey, the staged build plan) is in
`design-vision.md`; this file describes what exists and why it's shaped this way.

## Module layout (`src/`)

- `types.ts` — the contract types: `EditEvent` in, `ContextPayload` out, plus
  `FileChange`, `ExpandedHunk`, `TimelineStep`, `IntentSignals`.
- `git.ts` — `Git`: a thin wrapper over the git CLI, always pointed at an
  isolated `GIT_DIR` + `GIT_INDEX_FILE` so no working tree is involved.
- `shadow-repo.ts` — `ShadowRepo`: the throwaway two-tier history.
- `scope.ts` — language-aware scope expansion (brace/python/markdown/text).
- `context.ts` — turns a consolidated drain into a `ContextPayload`.
- `session.ts` — `AmbientSession`: the timing-free engine tying the above
  together. The unit of testability.
- `watcher.ts` — `AmbientRunner`: the filesystem adapter + timing policy.
- `cli.ts` — `simulate` and `watch` commands.

`pi/ambient-agent.ts` is the pi extension wrapper; it imports `AmbientRunner`
and adds only pi-specific wiring.

## The shadow repository

A bare git repo in a temp dir, with a private index file, recording the editing
session as a two-tier history:

```
main:     baseline ----------- M1 ----------- M2 ...   (consolidated drains)
                                |              |
drain-1:  *--*--*--*------------+              |
          (debounced snapshots)                |
drain-2:                        *--*--*--------+
```

Key implementation choices:

- **No working tree, ever.** Blobs are written from content via
  `git hash-object -w --stdin --path`, staged into the private index with
  `update-index --cacheinfo`, turned into a tree with `write-tree`, and
  committed with `commit-tree`. The human can be live-editing the same files;
  the shadow repo never reads or writes their working tree.
- **`--first-parent main`** yields the clean net-delta timeline; a merge's
  **second parent** preserves the keystroke journey. Both views, one mechanism.
- **Consolidation is a `--no-ff` merge built with `commit-tree`**, tree = the
  drain tip's tree (i.e. "current state"), which sidesteps conflicts entirely.
- **Throwaway.** `destroy()` removes the temp dir; the real repo is untouched.

`buildTree` rebuilds the full tree from the current watched set each snapshot
(empty the index, stage every file). This keeps the tree exactly in sync with
the watched set — including deletions — and avoids index drift, at the cost of
staging N blobs per snapshot (cheap for a watched set).

## The engine is timing-free

`AmbientSession` contains **no timers**. It exposes `recordEdit` (buffer latest
content), `snapshot` (commit the buffer onto the drain branch), and `drain`
(snapshot + consolidate + build context). All time-based behavior lives in
`AmbientRunner` (debounced snapshot cadence; quiet-period review cadence). This
is the seam that makes the core deterministic and unit-testable, and lets the pi
wrapper substitute pi's idle signal for the quiet-period trigger
(`autoReview: false`).

Two decoupled cadences, exactly as the vision requires:

- **Snapshot cadence** — frequent, debounced; captures the journey.
- **Drain/review cadence** — driven by "attention returns" (quiet period
  standalone; pi idle when embedded); defines review boundaries.

## Context construction (`context.ts`)

1. `nameStatus(from, to)` → per-file add/modify/delete.
2. Per file: a `--function-context` unified diff (scope-expanded for free where
   git knows the language) for `FileChange.diff`.
3. A `--unified=0` diff feeds `parseNewRanges`, which extracts precise changed
   new-side line ranges; each range is run through `expandScope` to produce the
   complete enclosing unit (`ExpandedHunk`), deduped when several edits share one
   scope.
4. `buildTimeline` diffs each incremental snapshot against its parent to
   reconstruct the ordered edit progression with per-step line ranges.
5. `inferIntent` scans the post-edit state for completeness signals.
6. `renderPrompt` lays it out primacy/recency-aware: task at top, timeline, then
   the scope-expanded diff, then the output contract restated at the bottom.

### Scope expansion

Dependency-free heuristics today, behind an interface a tree-sitter backend
could implement later:

- **brace** — balance-match the enclosing `{...}`; pull the signature/comment up;
  if no enclosing block (a new top-level declaration), use the block the change
  itself opens.
- **python** — indentation walk to the nearest `def`/`class`, body by deeper
  indentation.
- **markdown** — nearest heading up; section ends at the next same/higher
  heading.
- A `maxLines` cap keeps a pathological file from blowing up the payload.

## The pi wrapper boundary

`pi/ambient-agent.ts` does only:

- `session_start` → construct `AmbientRunner(autoReview:false)` and `start()`.
- `agent_end` → if idle and `runner.hasPendingReview`, call `runner.review()`;
  the review's `onReview` injects the payload via `pi.sendMessage` (`triggerTurn`
  when idle, `deliverAs` steer/followUp by posture, `display:false`) and updates
  the side widget.
- `session_shutdown` → `runner.dispose()`.

The pi types are declared minimally inline so the wrapper documents its exact
dependencies and typechecks without pi installed; swap for the real import when
embedding.

## Status vs. the staged build plan

- Stage 1 (watcher + shadow repo + net diff + scope expansion) — **done**.
- Stage 2 (attention-driven drain + arbiter) — engine + standalone done; pi-side
  idle-drive implemented in the wrapper, untested against a live pi build.
- Stage 3 (rich context) — timeline, scope expansion, intent, layered/cacheable
  prompt **done**; referenced-symbol/repo-map/related-tests **not yet**.
- Stages 4–5 (journey view UI, options UI, prose generalization) — **not yet**.

## Open questions

- Prose context strategy beyond timeline + section expansion.
- Feedback-loop guard once the agent writes edits back (origin-tagged commits;
  review only human-authored ranges).
- Arbiter eagerness (steer vs. followUp) and a global mute.
- Whether to add tree-sitter/LSP, or stay heuristic for the PoC.
