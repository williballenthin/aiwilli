# Global Observational Memory System

## Design & Specification

---

## Part I: What We're Building and Why

### The Problem

When working heavily with software engineering agents (Claude Code, Pi, Codex, Gemini, etc.), kicking off dozens of threads per hour across multiple projects, a significant amount of knowledge is generated and then lost. Each new agent session starts cold — unaware of preferences expressed in other sessions, decisions made earlier that day, or patterns that have emerged across projects over weeks.

This manifests as several concrete friction points:

**Repeated self-explanation.** Preferences like "never use mocks in tests" or "prefer behavioral specs over implementation docs" get restated across sessions, across projects, across days. The human becomes a manual relay of their own patterns.

**Lost context between sessions.** A decision made in one thread (e.g., "we decided to restructure the auth module") doesn't propagate to other concurrent threads working in the same project, let alone to future sessions.

**Drifting project documentation.** When many small changes are made through quick agent threads, project-level artifacts like spec files and agents.md fall out of sync with reality. The human forgets to ask the agent to update them, and the agents don't know to do it on their own.

**No awareness of cross-project patterns.** Work happening in one project might be relevant to another — shared libraries, repeated approaches, converging design decisions — but no system surfaces these connections.

### The Vision

A background system that watches the stream of all agent interactions and maintains a living model of how the user works, what they care about, and what they're doing right now. This model is stored as a simple markdown file on the filesystem, readable by any agent in any future session. The system learns and updates autonomously, surprising the user with observations they didn't expect, surfacing patterns that emerge organically rather than being manually catalogued.

The global memory file becomes a shared substrate: new agent sessions read it to understand context before their first message. The user reads it to see what the system is learning about them. And downstream applications — spec maintenance, proactive suggestions, even automated issue creation — can eventually build on top of it.

### Values and Philosophy

**Emergence over enumeration.** The system should discover patterns, not just file observations into predefined categories. The LLM doing the analysis should be invited to notice surprising things, identify shifts in thinking, and surface connections the user hasn't explicitly stated. The taxonomy of signals should grow organically.

**Git as the source of truth.** The entire `~/.agent-memory/` directory (minus `state.db`) is a git repository. Every operation — new observations, reflector consolidations, memory updates — is committed with a descriptive message that traces back to the source material. This provides full history, easy rollback if the system goes off the rails, and a human-readable audit trail of how the memory evolved. Commit messages should be specific: not "updated observations" but "3 observations from Pi session 'auth-refactor' (id: abc-123-def)."

**Files over databases.** The primary outputs are markdown files on the filesystem. Agents already know how to read files. Humans can read them too. They're diffable in git, greppable, and won't break when tooling changes. A minimal SQLite database is acceptable for tracking processing state (which messages have been analyzed), but it's plumbing, not product — and is gitignored.

**Decoupled from any agent harness.** The system must not be an extension of Pi, Claude Code, or any specific agent framework. These tools change every few months. The system runs independently — a daemon that polls for session transcripts from whatever harness produced them. The filesystem is the integration layer.

**Minimal infrastructure, maximal tolerance for change.** No heavy databases, no migrations, no complex state management. Idempotent operations where possible. If the SQLite tracking database gets corrupted, the worst case is reprocessing some already-seen messages — not data loss.

**Human-in-the-loop for high-trust artifacts.** The global memory file can be updated autonomously. But when observations suggest changes to project spec files or the canonical agents.md in git, those should be proposed, not auto-committed. The system should flag what it thinks needs updating and let the human decide.

**Start with frontier models, distill later.** Getting the observation extraction right is the hard problem. Use the best available models (Claude, GPT-4o) to prototype and iterate on what good observations look like. Once the ontology is clear and there's training data, then explore fine-tuning smaller local models (4B-8B parameter range) for fast, cheap, local inference.

### Inspirations and Prior Art

**Mastra Observational Memory** is the closest existing system. It uses a two-stage pipeline — an Observer that compresses verbose message history into concise notes, and a Reflector that condenses those notes when they pile up. The result is a three-tier context: recent messages, observations, and reflections. Mastra's async buffering (pre-computing observations in the background) and token-budget triggers are well-designed.

However, Mastra OM solves a different problem. It operates within a single agent's context window to prevent context rot during long sessions. It's tightly coupled to the Mastra agent framework. Its observations are task-oriented ("user asked about middleware configuration") rather than meta-level ("user consistently rejects mocking across projects").

**What we borrow from Mastra:**

- The two-stage observe-then-reflect architecture
- Timestamped observations with confidence/priority signals
- The concept of threshold-triggered consolidation
- The general shape of the three-tier memory hierarchy

**Where we diverge:**

- Our system sits outside and above all sessions, not inside any one of them
- Our observations are about the user's patterns, preferences, and focus — not about task progress
- We're decoupled from any agent framework
- Our output is a standalone file, not an injected context window
- We operate across all projects, not within a single conversation
- Observation extraction is a research area — we support multiple parallel extractors with different strategies, models, and prompts rather than a single fixed pipeline

---

## Part II: High-Level Implementation

### Architecture Overview

The system consists of three components running as a background daemon, plus a set of output files on the filesystem.

```
┌─────────────────────────────────────────────────────┐
│                  Session Sources                     │
│   (Pi transcripts, Claude Code logs, etc.)           │
└──────────────────────┬──────────────────────────────┘
                       │ polls for new messages
                       ▼
              ┌─────────────────┐
              │    Watcher      │
              │  (ingestion +   │
              │   cursor mgmt)  │
              └────────┬────────┘
                       │ new messages
          ┌────────────┼────────────┐
          ▼            ▼            ▼
   ┌────────────┐┌────────────┐┌────────────┐
   │ Extractor  ││ Extractor  ││ Extractor  │
   │ pairwise/  ││ window/    ││ session/   │  (parallel, pluggable)
   │ claude     ││ claude     ││ local-8b   │
   └─────┬──────┘└─────┬──────┘└─────┬──────┘
         │             │             │
         ▼             ▼             ▼
   observations/ observations/ observations/
   pairwise-     window-       session-
   claude/       claude/       local-8b/
         │             │             │
         └──────┬──────┘             │  (primary collections only)
                ▼                    │
       ┌─────────────────┐          │
       │    Reflector    │          │  (experimental, not yet
       │  (consolidation │          │   feeding the Reflector)
       │   + promotion)  │
       └────────┬────────┘
                │ updates
                ▼
┌─────────────────────────────────────────────────────┐
│               Output Files (filesystem)              │
│                                                      │
│   global_memory.md             - the living memory   │
│   observations/<extractor>/    - per-extractor daily  │
│     yyyy-mm-dd.md                observation logs    │
│   prompts/                     - versioned prompts   │
│   dashboard.html (optional)    - human inspection    │
└─────────────────────────────────────────────────────┘
```

### Component 1: The Watcher

**Purpose:** Discover new session activity and queue unprocessed messages for analysis.

**Behavior:**
- Runs on a timer (e.g., every 10-15 minutes) or can be triggered manually
- Scans known locations for session transcripts (Pi session storage, Claude Code conversation logs at `~/.claude/`, and any other configured sources)
- Maintains a SQLite database tracking: which sessions have been seen, which messages within each session have been processed, and timestamps
- Extracts new messages and makes them available to extractors for processing
- Handles multiple transcript formats via pluggable adapters — one for Pi's format, one for Claude Code's format, etc.

**Key design decisions:**
- The Watcher does not interpret message content. It only handles discovery and cursor management.
- If the SQLite database is lost, the Watcher can rebuild by reprocessing all transcripts (idempotent).
- New agent harnesses are supported by adding a new transcript adapter — a small module that knows where to find files and how to parse them into a common message format.

### Component 2: The Observer (Extractor Framework)

**Purpose:** Analyze session transcript content and extract raw observations.

**The extraction strategy is an active area of research.** How we prompt the model, which model we use, and what unit of transcript we feed it (a single message pair? a full session? a sliding window?) are all open questions. We expect to iterate significantly here before converging on a preferred approach — and may never fully converge, keeping multiple strategies running for different purposes.

To support this, the Observer is not a single extractor but a **framework for running multiple extractors in parallel**, each writing into its own observation collection. This allows side-by-side comparison of different techniques against the same transcript data.

#### Extractor Architecture

An extractor is a named configuration consisting of:

- **A prompt** — the instructions given to the LLM for what to look for and how to format observations
- **A model** — which LLM to use (frontier API, local small model, etc.)
- **An input strategy** — how transcript content is sliced and fed to the model:
  - *Pairwise*: assistant response + subsequent user response (the corrective signal)
  - *Sliding window*: N consecutive messages for broader context
  - *Full session*: the entire transcript at once (expensive but holistic)
  - *Cross-session*: messages from multiple recent sessions bundled together (for spotting patterns across threads)
  - Others as we discover them
- **An output collection** — the directory where this extractor writes its daily observation files

Each extractor writes to its own subdirectory under observations:

```
~/.agent-memory/observations/
  pairwise-claude/          ← extractor using pairwise input + Claude
    2025-02-19.md
    2025-02-20.md
  window-claude/            ← extractor using sliding window + Claude
    2025-02-19.md
  pairwise-local-8b/        ← extractor using pairwise input + local 8B model
    2025-02-19.md
  full-session-claude/      ← extractor processing whole sessions
    2025-02-19.md
```

This structure means:
- We can run multiple extractors against the same transcripts simultaneously
- We can compare output quality across strategies by reading the parallel daily files
- We can add or remove extractors without affecting others
- The Reflector can be configured to read from one or more collections
- An extractor can be experimental (we're just evaluating it) or promoted to primary (the Reflector uses it)

#### Extractor Configuration

Extractors are defined in config, something like:

```yaml
extractors:
  pairwise-claude:
    enabled: true
    primary: true          # Reflector reads from this collection
    model: claude-sonnet-4-20250514
    input_strategy: pairwise
    prompt: prompts/pairwise-v2.md
    context:
      include_global_memory: true

  window-claude:
    enabled: true
    primary: false         # experimental, not yet feeding the Reflector
    model: claude-sonnet-4-20250514
    input_strategy: sliding_window
    window_size: 20        # messages
    prompt: prompts/window-v1.md
    context:
      include_global_memory: true

  pairwise-local-8b:
    enabled: false         # disabled until we have a fine-tuned model
    model: local/llama-8b
    input_strategy: pairwise
    prompt: prompts/pairwise-local-v1.md
    context:
      include_global_memory: false  # keep it simple for the small model
```

#### What Extractors Look For

Regardless of strategy, extractors are generally looking for the same kinds of signals, though different input strategies may surface different ones. A pairwise extractor is good at catching corrections and caveats; a full-session extractor might be better at spotting focus shifts and narrative arcs.

**Signal taxonomy (starter set, expected to grow):**

| Signal Type | Description | Example |
|---|---|---|
| Preference reinforcement | User restates a known preference | "No, I said no mocks" (again) |
| Correction | User corrects agent behavior | "Don't use implementation details in the spec" |
| Redirection | User changes approach mid-task | "Actually let's use a different auth strategy" |
| Elaboration | User clarifies intent or meaning | "What I mean by behavioral spec is..." |
| Approval with caveat | User accepts work but notes a future preference | "This is fine but next time use X" |
| Focus shift | User's attention moves to a new area | Multiple threads now about project-Y, none about project-X |
| Novel pattern | Something the model notices that doesn't fit above | (emergent — let the LLM discover these) |

The model is explicitly encouraged to create new signal types when existing ones don't fit. The taxonomy is a starting point, not a constraint. Different extractors may discover different taxonomies — that's a feature.

#### Observation Format

Consistent across all extractors. Each observation retains a source reference —
the session transcript file path and message ID — so that an agent or human can
grep for the original content and see the full context. The `src:` field should
be specific enough that `grep -r "msg_id" ~/.pi/sessions/` (or equivalent)
locates the exact exchange.

```markdown
# Observations — 2025-02-19
# extractor: pairwise-claude (prompts/pairwise-v2.md, claude-sonnet-4-20250514)

## 14:30 — project-api-gateway

src: ~/.pi/sessions/abc123/transcript.jsonl msg:47-48

- [preference:reinforced] User again rejected mock-based testing, insisted on
  integration tests with real database connections. (Seen 12 times previously)
- [redirection] User abandoned the middleware approach for auth and switched to
  a guard-pattern at the route level. Reasoning: "middleware is too implicit,
  I want auth checks to be visible in the route definition."

## 14:45 — project-dashboard

src: ~/.claude/projects/dashboard/00f2a1.jsonl msg:12-13

- [novel] User is increasingly frustrated with verbose tool output cluttering
  context. Has mentioned this in 3 separate sessions today across 2 projects.
```

#### Evaluating Extractors

With parallel collections, evaluation becomes straightforward:

- **Manual review**: Read the daily files from two extractors side by side. Which one surfaces more useful observations? Which one produces noise?
- **Coverage comparison**: For a known set of "important moments" in a day's transcripts, which extractor caught them?
- **Reflector quality**: Run the Reflector against different collections and compare the resulting global memory updates. Which collection produces better consolidations?
- **Over time**: Track which extractors' observations actually get promoted to the durable layer by the Reflector. That's a proxy for usefulness.

This is genuinely a research process. We expect to iterate on prompts frequently, try different models as they become available, and experiment with input strategies. The extractor framework makes this cheap and safe to do.

### Component 3: The Reflector

**Purpose:** Periodically consolidate raw observations into the structured global memory file.

**Behavior:**
- Runs less frequently than extractors (e.g., daily, or when recent observation files exceed a size threshold)
- Reads the current global_memory.md and recent daily observation files from primary extractor collections (i.e., extractors marked `primary: true` in config)
- Sends both to a frontier LLM with a prompt that asks it to update the global memory:
  - Promote repeated or high-confidence observations to the durable layer
  - Update the active layer with current project focus and recent decisions
  - Age out stale items from the active layer
  - Archive or drop observations that are no longer relevant
  - Preserve observation counts and confidence signals
- Writes the updated global_memory.md
- Older daily observation files remain on disk as a historical record and can be re-read if the Reflector needs deeper lookback

**The Reflector should be conservative.** It's better to leave a weak observation in the recent layer for another cycle than to prematurely promote something to the durable layer. Durable preferences should have strong evidence — multiple observations across sessions and time.

### The Global Memory File

The central output artifact. Structured as a markdown document with temporal layers.

```markdown
# Global Memory

Last updated: 2025-02-19T18:00:00Z

## Durable Preferences and Patterns

These are stable, high-confidence observations about working style and
preferences. They have been observed consistently over time.

- **Testing philosophy**: Never use mocks. Always prefer integration tests
  with real dependencies. Design systems to enable this.
  [observed 14 times across 6 projects, first seen 2025-01-03]
- **Documentation style**: Spec files describe behavioral expectations from
  a user perspective — not implementation. Implementation goes in design
  docs. [observed 8 times across 4 projects]
- **Agent interaction pattern**: Prefers many short threads over long
  conversations. Typical session: give a focused task, review result, give
  feedback, move on. [observed consistently]
- ...

## Active Context

Current projects, focus areas, and recent significant decisions. Updated
as work patterns shift.

- **Currently active**: project-api-gateway (auth refactor),
  project-memory-system (this system), project-dashboard (on hold since 02-15)
- **Current focus**: Building observational memory infrastructure. Exploring
  small model fine-tuning for observation extraction.
- **Recent decisions**:
  - 2025-02-18: Switched project-api-gateway auth from middleware to
    route-level guards
  - 2025-02-17: Decided to use markdown over JSON for all memory/spec files
- ...

## Recent Observations

See daily observation files in `~/.agent-memory/observations/<extractor>/`
for raw, unprocessed notes with full source references.

Primary collection (pairwise-claude):
- [2025-02-19](observations/pairwise-claude/2025-02-19.md) — 7 observations across 3 projects
- [2025-02-18](observations/pairwise-claude/2025-02-18.md) — 12 observations across 2 projects
- ...
```

### Processing Pipeline (End-to-End)

1. User works with agents across multiple sessions and projects throughout the day
2. **Watcher** (every ~10 min): Scans transcript sources, finds new messages, records them in SQLite, makes them available to extractors
3. **Extractors** (every ~10 min, after Watcher): Each enabled extractor processes new messages according to its input strategy and appends to its own daily observation file in `observations/<extractor>/yyyy-mm-dd.md`. Commits results with source-tracing message.
4. **Reflector** (daily or threshold-triggered): Reads recent daily observation files from primary extractor collections + current global memory, produces updated global_memory.md. Commits with summary of what was promoted/updated/aged out.
5. When a new agent session starts, the agents.md file references or includes the global memory. The agent reads it and has context from the first message.
6. User can inspect observation collections from different extractors, compare quality, and promote experimental extractors to primary when satisfied. Full history available via `git log`.

### Technical Decisions

**Language:** Python. Widely supported, good LLM client libraries, easy to script and run via cron.

**LLM for extractors/Reflector:** Start with Claude (via API) or GPT-4o. The extractor prompts are the critical piece — iterate on them before anything else. Different extractors can use different models.

**Session transcript adapters:** Small Python modules, one per agent harness. Each implements a common interface: given a session directory/file, return a list of messages in a standard format (role, content, timestamp, session_id, project).

**State tracking:** SQLite database with minimal schema — sessions seen, messages processed, timestamps. If lost, rebuild by reprocessing (idempotent).

**Scheduling:** Start with a simple cron job or a Python script with `time.sleep()` loop. No need for task queues or orchestration frameworks.

**File locations:**
- `~/.agent-memory/` — a git repository (initialized on first run)
- `~/.agent-memory/global_memory.md` — the main artifact
- `~/.agent-memory/observations/<extractor>/yyyy-mm-dd.md` — daily observation files, one directory per extractor
- `~/.agent-memory/prompts/` — extractor prompt files, versioned by name
- `~/.agent-memory/state.db` — SQLite processing state (gitignored)
- `~/.agent-memory/config.yaml` — extractor definitions, transcript source locations, LLM settings, scheduling
- `~/.agent-memory/.gitignore` — excludes `state.db`

**Git commit strategy:**

Every pipeline operation commits its results with a message that explains what happened and where it came from. Commits happen automatically at each stage boundary — after extractors run, after the Reflector runs, etc.

Example commit messages:
```
observations: 3 from pairwise-claude — Pi session 'auth-refactor' (id: abc-123-def)
observations: 1 from window-claude — Claude Code session 'fix-routing' (id: 00f2a1)
observations: 5 from pairwise-claude — 2 Pi sessions, 1 Claude Code session
reflector: consolidated 2025-02-19 observations into global memory — promoted 2 to durable, updated active context
reflector: aged out 3 stale items from active context
config: added new extractor window-gemini-flash
```

The commit messages serve as both an audit trail and a quick way to understand the system's activity via `git log --oneline`. If the system produces bad observations or the Reflector makes a poor consolidation, `git revert` or `git reset` cleanly rolls back to a known good state.

The Watcher, extractors, and Reflector should each commit after completing their work. If an extractor processes messages from multiple sessions in one run, it can batch them into a single commit with a summary message listing the sources.

### What's on the Roadmap but Not in v1

These are directions the system could grow into, but are explicitly deferred:

- **Spec drift detection and automated update proposals.** The same observation pipeline could identify when project behavior has changed and propose spec file updates. Deferred because better prompting in agents.md may solve this more simply.
- **Proactive suggestions.** "You've been doing X across three projects — have you considered extracting a shared library?" or "Based on your recent work, here's a GitHub issue you might want to create." Wild and exciting, but requires the core observation pipeline to be solid first.
- **Small model fine-tuning.** Once the frontier model extractors produce enough good examples, distill into a 4B-8B parameter model that runs locally and fast. The session transcripts are a gold mine of training data. A fine-tuned small model becomes just another extractor in the framework.
- **Cross-machine synchronization.** The global memory file is currently system-local. Durable, stable conclusions get manually promoted to the personal agents.md in git, which propagates everywhere. True real-time sync is not needed now.
- **Within-session context compression.** Mastra-style observational memory that compresses a single conversation's context window. Valuable but orthogonal to the global memory system. Could be built later using similar techniques.

### What to Build First

The highest-leverage first step is to **validate that observation extraction produces useful results.** Everything else is plumbing. Since the extraction strategy is a research area, the plan starts with experimentation.

Concrete plan:

1. **Examine actual session transcript formats** for Pi and Claude Code. Understand file paths, data structures, message formats.
2. **Write two or three extractor prompts** with different input strategies (at minimum: pairwise and sliding window) and test them against real transcript data. Compare outputs. Iterate until at least one produces observations that are genuinely interesting — surprising, cross-cutting, and actionable.
3. **Build the Watcher** with one transcript adapter (whichever harness has the most accessible format).
4. **Build the extractor framework** — the config-driven runner that can execute multiple extractors in parallel against the Watcher's output, each writing to its own collection.
5. **Run multiple extractors for a few days** and compare the daily observation files. Which strategies surface useful signals? Which produce noise? Promote the best to primary.
6. **Build the Reflector** and the global_memory.md consolidation pass, reading from the primary collection(s).
7. **Integrate with agent sessions** by referencing global_memory.md from agents.md.
