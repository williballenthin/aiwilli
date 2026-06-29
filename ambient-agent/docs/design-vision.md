# Ambient Editing Companion — Design Document

> **Status:** Draft for review · **Author:** Willi (with Claude) · **Target runtime:** `pi` coding agent (`earendil-works/pi` / `badlogic/pi-mono`)
> **One-line:** A background agent that watches your live edits to source and prose files, and offers commentary/ideas in real time — without you prompting it — while still letting you drop into normal chat.

> This is the original product vision. For what is actually implemented, see `design.md` and `spec.md`.

---

## 1. Goal

Recover the experience of pair-working in an editor with a collaborator whose skills are on par with Claude Code / `pi` — but in a **live, ambient, real-time** way rather than the prompt-and-wait loop we use today.

Concretely, the workflows we want to escape and the one we want to build:

- **Today (what we already do well):** write a spec → hand it to an agent; or directly prompt "do X." Both work, but both require us to *stop editing and address the agent*.
- **What's been lost:** the feeling of someone editing *alongside* you who notices what you're doing and chimes in — "you said this, have you also thought about that?" — without being summoned into a chat window or tagged in a comment.
- **What we want to build:** as you work in your editor of choice, an agent quietly watches the file, and either (a) surfaces live commentary/ideas in a side view, or (b) proposes edits. You never have to switch context to "ask" it; it's *present*.

### Non-goals (for the proof-of-concept)
- Not trying to replace direct prompting or spec-driven flows — this sits *alongside* them.
- Not building a new editor or a custom multiplayer protocol.
- Not relying on editor/IDE telemetry, cursor position, LSP state, browsing history, or filesystem access-time (`atime`). The harness deliberately assumes **only filesystem events**: which file changed, when, and the byte/line range.

---

## 2. Why this is worth building (the frontier, and what exists today)

We started by asking: *does anything do this today?* The honest answer from the research is **no shipping product gives you a Claude-Code-skill-level peer that watches a long editing session and proactively does substantive work, unprompted, in your own editor.** Everything on the market falls into one of three buckets:

1. **Reactive next-edit prediction** — Zed Zeta/Zeta2.1, GitHub Copilot NES, Cursor Tab, Continue.dev Next Edit, Inception Mercury. Ambient in *timing*, but bounded to local completions/suggestions, not a collaborator doing real work.
2. **Prompt-and-wait agents** — Claude Code, Cursor Agent, Zed Agent, Aider chat. Substantive, but you must summon them.
3. **Comment-triggered agents** — Aider `--watch-files` (reacts to `AI!`/`AI?` comments). Closest to "in your editor," but still requires you to tag it.

The nearest thing to genuine ambience is **Windsurf Cascade "Flow State"** ("aware of your real-time actions… surface proactive suggestions… without requiring an explicit prompt"), but it's bounded to suggestions and locked to a proprietary VS Code fork.

**Conclusion that set our direction:** the ambient-peer experience is a real, under-explored gap, and to get it we have to build it. The two viable substrates were Claude Code (headless/streaming/hooks) and `pi`. We chose **`pi`** because it's purpose-built as an embeddable, event-driven harness with the exact primitives we need (covered in §6).

---

## 3. Proposed solution (architecture overview)

A `pi` **extension** (in-process plugin) that:

1. **Watches** a set of files via a filesystem watcher (debounced).
2. **Tracks edits** in a **hidden temporary git repository** (a "shadow repo") that lives outside the project, so we can consolidate many small keystroke-level edits into one meaningful net diff.
3. **Consolidates on the agent's attention**, not on a timer: the queue of edits is "drained" when the agent turns its attention to it. The diff handed to the agent is the *net* change since it last looked.
4. **Constructs rich context** around that diff (tree-sitter scope expansion, referenced symbols, an edit-progression timeline, etc.) and injects it into the `pi` conversation as a turn.
5. **Lets the agent arbitrate attention**: respond to new edits, or yield to the human; and be interruptible/steerable back to fresh edits if the human is slow while more edits arrive.
6. **Renders** commentary and agent-offered options into `pi`'s existing TUI (side widget + interactive selectors), so the human can read, think, and occasionally respond — inheriting the chat UI for free.

### The interface contract (important boundary)
**The agent is not aware of the git backend.** The shadow repo, the branching, the merge commits, the `last-reviewed` pointer — all of it is an implementation detail of the harness. The agent only ever receives a constructed context payload ("here's what changed since you last looked") and emits commentary/ideas/proposed edits. This keeps the agent's context clean and lets us swap the backend later without touching the agent contract. The entire API surface between harness and agent is **"a distilled diff + supporting context" in, "commentary/edits" out.**

---

## 4. Design decisions & trade-offs (the *why*)

### 4.1 Why a file-watcher + shadow-git backend (not CRDT, not editor integration)
- **CRDT-as-a-peer** is elegant but web/browser-native and forces a specific editor. A filesystem watcher is the lowest-common-denominator that works everywhere.
- **The watcher constraint is deliberate:** only `{file, timestamp, range}`. No editor telemetry, no `atime`. We compensate with the **edit timeline** (§5.3).

### 4.2 Why consolidate edits — and why "drain on attention," not on a timer
1. Batch edits so the agent sees the *merged* diff, not every keystroke.
2. Keep the *journey* available too (incremental detail on demand).
3. The drain boundary is **the agent's attention**, not a fixed interval. The queue drains exactly when the agent returns. Self-pacing / backpressure-aware; dissolves net-vs-journey tension; inverts control to the agent.

### 4.3 Why a *temporary, shadow* git repo
- Two repos tracking one file is fine: point `GIT_DIR`/`GIT_WORK_TREE`/`GIT_INDEX_FILE` at independent locations.
- Throwaway: `rm -rf` on stop. Commits (cheap, readable history) over bare trees, optimized later only if needed.

### 4.4 Why the two-tier branch/merge history
- Incremental `●` snapshots on `drain-N` branches; `--no-ff` merge commits `Mn` on `main`.
- `git log --first-parent main` → clean net deltas; second parent → journey.
- Build via `git commit-tree` so the working tree is never touched; delete `drain-N` refs after merging.

### 4.5 Why the inverted-control / "agent-as-attention-arbiter" model
- The event stream drives; the agent arbitrates attention; it's interruptible/steerable; the human keeps a normal chat fallback.

### 4.6 Why build as a `pi` *extension*
- Avoid rebuilding the chat UI while getting injection, steering, idle-wake, and background watchers. (Option D, multi-attach to one session, is impossible — single frontend per session, issue #5700.)

---

## 5. Context construction (what we feed the agent)

### 5.1 Baseline: tree-sitter-expanded net diff
Expand the net diff to the enclosing syntactic scope rather than a fixed line count.

### 5.2 High-leverage additions (for structured code)
1. Referenced symbol context. 2. Repo-map blast radius (Aider-style PageRank). 3. Related tests. 4. Conventions/preferences.

### 5.3 The universal signal: edit-progression timeline
An ordered list of edit steps reconstructed from incremental snapshots, most recent last, with the consolidated net diff. Recency rule: treat the most recent edit as intentional.

### 5.4 Prose / Markdown files (open design area)
Structured-code apparatus evaporates for prose. The edit timeline is the cross-cutting anchor; a parallel prose-context strategy is not yet designed.

### 5.5 Diff representation & format
Prefer search/replace or function-level structured hunks; layered payload exploiting primacy/recency; token budgeting; cache-friendly stable prefixes.

### 5.6 Intent / "when to stay quiet"
Infer completeness (parse errors, empty bodies, TODO), clustering/recency, cross-file sequencing; noise control with thresholds and a "WIP ⇒ stay silent unless blocking" gate.

---

## 6. pi integration: the primitives we rely on

- **Extension system:** TS modules with lifecycle hooks (`session_start`, `agent_start`/`agent_end`, `turn_*`, `message_*`, `tool_call`, `context`, `input`, `session_shutdown`).
- **Input injection:** `pi.sendUserMessage` (user-role turn) and `pi.sendMessage` (custom message, can be silent context).
- **Steering / queuing / idle-wake:** `deliverAs: "steer" | "followUp" | "nextTurn"` and `triggerTurn: true`; `ctx.isIdle()`, `ctx.hasPendingMessages()`, `ctx.abort()`.
- **Background watcher placement:** start in `session_start`, clean up in `session_shutdown`.
- **Synthetic-turn distinction:** `input.source: "interactive" | "rpc" | "extension"`.
- **UI without a custom frontend:** `ctx.ui.setWidget`, `ctx.ui.select`/`confirm`/`custom`; guard TUI-only methods with `ctx.mode`.
- **Prior art:** official `file-trigger.ts`, `send-user-message.ts`, JoelClaw inngest-monitor.

---

## 7. Key risks, unknowns & caveats

- No multi-attach to one session (#5700); no dedicated idle event (synthesize from `agent_end` + `ctx.isIdle()`); `sendUserMessage`-after-`newSession` drop (#2860/#3021); steering isn't a hard mid-tool kill; some UI methods are TUI-only; package-scope flux (`@earendil-works/*` vs `@mariozechner/*`).
- Feedback loops (agent writes trip the watcher) are the top engineering risk — debounce, origin-tag commits, review only human-drain ranges, "comment only unless asked."
- Prose context undesigned; over-large diffs unreviewable; surface agent edits as proposed diffs, never silent writes.

---

## 8. Build plan (staged)

0. De-risk pi primitives. 1. Watcher + shadow repo + net diff. 2. Attention-driven drain + arbiter. 3. Rich context. 4. Two-tier history + journey view; options UI. 5. Prose generalization. Escalation triggers to SDK/RPC/separate-process watcher as needed.

---

## 9. Open questions
- Prose/Markdown context strategy; debounce/"attention returns" policy; default arbiter posture; where proposed edits surface; tree-sitter-only vs. LSP for the PoC.
