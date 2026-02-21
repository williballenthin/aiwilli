# Global Observational Memory System — Specification

Status: Draft (v0.4 remote-only eval capable)  
Last updated: 2026-02-21

## 1) Purpose

This system maintains a **global, persistent memory** of how the user works across many agent sessions (Pi, Claude Code, etc.).

From a user perspective, it should:

- reduce repeated self-explanation,
- carry context across concurrent and future sessions,
- surface stable preferences and recent focus,
- stay readable and inspectable as plain files,
- preserve history via git.

This document describes **what the system does** and **what users see**. It intentionally avoids implementation internals.

## 1.1) Naming and command surface (decided)

- Product/project short name: **memory-claw**
- Python package name: **`memory_claw`**
- CLI executable name: **`memory-claw`**

CLI command contract for v1:

- `memory-claw init`
- `memory-claw run once`
- `memory-claw run daemon`
- `memory-claw watcher run`
- `memory-claw extractors run [--extractor <name>]`
- `memory-claw reflector run`
- `memory-claw status`
- `memory-claw eval run [--sample-size N] [--extractor <name>] [--workers N]`

Global runtime override supported in first pass:

- `--memory-root /path/to/root` on all commands
- `MEMORY_CLAW_ROOT=/path/to/root` environment variable

## 1.2) Runtime behavior (implemented)

Current implementation uses a remote-LLM-assisted pipeline for extraction/reflection:

1. `init` bootstraps filesystem layout, default `config.yaml`, prompt stubs, `.gitignore`, and initializes git.
2. Watcher ingests normalized transcript messages from configured Pi/Claude roots into `state.db`.
3. Extractors run from DB-backed cursors and write daily observation markdown files.
4. Reflector rewrites `global_memory.md` by preserving or updating sections and refreshing recent-observation links.
5. Git commits are created at init, extractor writes, and reflector writes when files changed.
6. Observation extraction and reflection are remote-LLM-only stages.
   - Runtime requires remote LLM availability for these stages.
   - No local heuristic fallback path is used.
   - If remote calls fail (missing key, request failure, invalid output after retries), stage command fails.
7. `run once` executes watcher + extractors + reflector in order, and skips reflector if extractor stage fails.
8. LLM usage/cost is tracked in `costs.jsonl` and surfaced in CLI output/status.

---

## 2) Product Scope (User-Facing)

### In scope (decided)

1. Background ingestion of agent transcripts from multiple harnesses.
2. Extraction of observations into daily markdown logs.
3. Periodic consolidation into `global_memory.md`.
4. Git history of all memory artifacts (except local processing DB).
5. Parallel extractors with different prompts/models/strategies.

### Out of scope for v1 (decided)

- Auto-editing project specs or `AGENTS.md` files.
- Automatic issue creation / proactive planning suggestions.
- Cross-machine real-time sync.
- Within-session token-window compression.

---

## 3) Primary User Interface: Filesystem

The main interface is a directory on disk:

- Default location: `~/.memory-claw/`
- It is a git repo.
- User and agents read/write through files, not APIs.

### Directory contract

```text
~/.memory-claw/
  global_memory.md
  config.yaml
  prompts/
    *.md
  observations/
    <extractor-name>/
      yyyy-mm-dd.md
  eval/
    runs/
      <run-id>/
        observer_cases.jsonl
        reflector_cases.jsonl
        report.md
  state.db              (internal, gitignored)
  costs.jsonl           (LLM usage/cost ledger)
  .gitignore
```

### Why this interface

- Works with any harness/tool that can read files.
- Human-readable and diffable.
- Easy rollback with git.
- Minimal coupling to changing agent frameworks.

---

## 4) User-Visible Behavior

## 4.1 Continuous operation

The system runs in the background on a schedule (roughly every 10–15 minutes for ingestion/extraction; less frequently for reflection) and can also be triggered manually.

Expected user-visible effect:

- observation files are appended during the day,
- `global_memory.md` updates periodically,
- git history shows what changed and why.

## 4.2 Transcript discovery

The system watches known transcript roots (configurable), including at minimum:

- Pi transcripts under `~/.pi/agent/sessions/`
- Claude Code transcripts under `~/.claude/projects/`

Claude subagent transcripts are excluded from ingestion because they are not direct user interactions.

It should tolerate new sessions appearing, sessions being appended over time, and occasional parser failures without stopping the whole pipeline.

## 4.3 Observation extraction

Each enabled extractor writes to its own daily file:

- `observations/<extractor>/yyyy-mm-dd.md`

Multiple extractors may process the same source material in parallel.

Extractors can be marked:

- `primary: true` (used by Reflector)
- `primary: false` (experimental only)

Extractor context window (implemented):

- current transcript chunk,
- optional `global_memory.md` snapshot,
- project documentation context (README + relevant `AGENTS.md` / `CLAUDE.md` when discoverable),
- prior rolling observations for the same session (latest ~5),
- few-shot format/examples from prompt guidance.

Pairwise extraction includes both:
- assistant→user chunks (tool messages may appear between), and
- the first user turn in a session as a single-message chunk when no assistant precedes it.

Remote observer prompt assembly uses a fixed actor-oriented layout to improve consistency and context quality. The prompt is structured in this order:

1. your role
2. your task
3. a list of what is coming
4. background
5. few-shot examples (good and bad)
6. project README
7. agent context files
8. prior observations
9. task (repeat)
10. input data (messages from session)
11. task (repeat)

Remote extractor outputs plain text lines (one observation per line), and runtime code converts those lines into structured observation items.

Format policy is strict:
- accepted observation line format: `- <importance> [signal_type] summary | why: reason`
- allowed importance markers: `🔴` (high), `🟡` (medium), `🟢` (low)
- multiple observation lines are allowed for a single message/chunk when distinct signals exist
- accepted empty response: exactly `(none)`
- if output is malformed, inference is re-run (no tolerant parsing).

## 4.4 Reflection and memory consolidation

Reflector updates `global_memory.md` by combining:

- current `global_memory.md`
- recent observation files from **primary** extractors
- recent observation links for the "Recent Observations" section

It should be conservative about promoting new durable preferences.

Remote reflector prompt assembly uses the same actor-oriented ordered layout as observer prompts (role, task, what-is-coming list, background, few-shot good/bad, project README, agent context files, prior observations, task repeat, input data, task repeat). In reflector runs, the "input data" section contains session-derived observation artifacts (links + recent observation markdown contents) rather than raw transcript messages.

Remote reflector output contract is markdown-first: return full `global_memory.md` content directly (no JSON requirement), with strict runtime validation of required sections.

If reflector output format is invalid (e.g., preamble/JSON/code-fence/missing sections), inference is re-run rather than permissively repaired.

## 4.5 Git behavior

Pipeline stages create commits with descriptive source-tracing messages.

Examples:

- `observations: 3 from pairwise-oss-120b — Pi session 'auth-refactor' (id: abc-123-def)`
- `reflector: consolidated 2026-02-21 observations — promoted 2 to durable`

If output quality regresses, user can revert in git.

## 4.6 Evaluation workflow

`memory-claw eval run` performs a sampled quality evaluation pass that captures actor context and outputs for human review.

Expected artifacts per run:

- `eval/runs/<run-id>/observer_cases.jsonl` — sampled observer cases with chunk context, prompt attempts, raw LLM responses, and parsed observation lines.
- `eval/runs/<run-id>/reflector_cases.jsonl` — reflector input/output trace for the sampled run.
- `eval/runs/<run-id>/report.md` — human-friendly review document with context excerpts, observed/reflected outputs, and feedback placeholders.

---

## 5) Data Shapes (User-Facing Files)

## 5.1 `global_memory.md`

Canonical human/agent-readable memory artifact.

Expected sections:

1. Durable Preferences and Patterns
2. Active Context
3. Recent Observations (links to daily files)

Example skeleton:

```markdown
# Global Memory

Last updated: 2026-02-21T18:00:00Z

## Durable Preferences and Patterns
- ...

## Active Context
- ...

## Recent Observations
- [2026-02-21](observations/pairwise-oss-120b/2026-02-21.md) — ...
```

## 5.2 Observation daily files

Per extractor, per day markdown file. Each entry should include source traceability.

Required characteristics:

- timestamped sections,
- project/session context,
- source reference (`src:` transcript path + message IDs/range),
- structured signal tags,
- per-observation importance (`🔴`, `🟡`, `🟢`),
- short `why` rationale describing inferred user intent/value.

Extractor tags are strategy/model dependent and may include emergent labels (to be normalized in a future pass).

Example:

```markdown
# Observations — 2026-02-21
# extractor: pairwise-oss-120b (prompts/pairwise-v2.md, openai/gpt-oss-120b)

## 14:30 — project-api-gateway
src: ~/.pi/agent/sessions/...jsonl msg:c0d19143-a6094a3a

- 🔴 [preference:reinforced] ... | why: ...
- 🟡 [redirection] ... | why: ...
```

## 5.3 `config.yaml`

User-managed runtime configuration. Includes:

- transcript sources,
- extractor definitions,
- model/provider configuration,
- scheduling,
- reflector settings.

Example shape:

```yaml
llm:
  provider: openrouter
  api_key_env: OPENROUTER_API_KEY
  timeout_seconds: 60
  max_run_cost_usd: 2.0
  max_run_calls: 400

extractors:
  pairwise-oss-120b:
    enabled: true
    primary: true
    model: openai/gpt-oss-120b
    input_strategy: pairwise
    prompt: prompts/pairwise-v2.md
    context:
      include_global_memory: true
```

## 5.4 Prompt files

Prompt instructions are first-class, versioned files in `prompts/`.

Users can iterate on prompt quality without changing code.

Current expected prompt content style includes:

- extractor prompts: line-oriented output guidance (one observation per line with importance + why),
- reflector prompts: full-markdown output guidance,
- terminology constraints,
- length/quality constraints,
- few-shot examples for observation shape and signal naming,
- actor-specific override guidance layered into a runtime prompt scaffold that always includes: role, task, upcoming-section list, background, good/bad examples, project README, agent context files, prior observations, repeated task reminders, and explicit input-data section.

## 5.5 Evaluation artifacts

`memory-claw eval run` emits review artifacts:

- `observer_cases.jsonl`: sampled observer-case records containing chunk context, prior-observation context, LLM prompt/response attempts, parsed observation items (`importance`, `signal_type`, `summary`, `why`), and any errors.
- `reflector_cases.jsonl`: reflector input/output trace for the sampled run.
- `report.md`: reviewer-friendly markdown with context/output excerpts and feedback placeholders (good/bad/notes).

---

## 6) User Interactions

Users interact by:

1. Reading `global_memory.md`.
2. Inspecting observation files per extractor for quality/noise.
3. Adjusting `config.yaml` (enable/disable/promote extractors).
4. Updating prompt files.
5. Running explicit CLI commands (`run once`, `status`, stage-specific `... run`).
6. Reviewing git history and rolling back if needed.
7. Monitoring LLM usage/cost through command output, `memory-claw status`, and `costs.jsonl`.
8. Running sampled quality evaluations with `memory-claw eval run` and reviewing generated artifacts under `eval/runs/<run-id>/`.

No vendor-specific UI is required.

---

## 7) Defined Decisions (So Far)

1. **Primary artifact is markdown on filesystem.**  
   Rationale: readable by humans + agents, diffable, greppable.

2. **Git is source of truth for memory artifacts.**  
   Rationale: audit trail + rollback.

3. **Small SQLite DB is allowed for processing state only.**  
   Rationale: reliable cursor tracking without product lock-in.

4. **System is decoupled from any one harness.**  
   Rationale: harnesses evolve quickly.

5. **Observe → Reflect two-stage pipeline.**  
   Rationale: separate raw extraction from durable consolidation.

6. **Multiple extractors run in parallel.**  
   Rationale: extraction quality is an active research area.

7. **Python implementation.**

8. **OpenRouter backend is implemented for remote extraction/reflection.**  
   Observation extraction and reflection are remote-only stages.

9. **PydanticAI remains a future integration option, not currently required.**  
   Current runtime uses a direct OpenAI-compatible HTTP path.

10. **Human-in-loop for high-trust downstream artifacts.**  
    Rationale: do not auto-edit canonical project docs/specs in v1.

11. **Stable naming convention for implementation surface.**  
    Rationale: use `memory-claw` (CLI/project) and `memory_claw` (Python package) consistently.

12. **Initial observation extraction model is `openai/gpt-oss-120b`.**  
    Rationale: strong quality/cost tradeoff for extraction tasks that are primarily contextual and instruction-following rather than highly novel reasoning.

13. **Claude subagent transcripts are excluded from ingestion/evaluation.**  
    Rationale: they are not direct user interactions and introduce off-target signal noise.

---

## 8) Behavioral Guarantees

1. **Best-effort idempotency:** if state is lost/corrupted, system can reprocess transcripts without data loss to source transcripts.
2. **Traceability:** observations should cite transcript origin sufficiently for manual verification.
3. **Conservative durability:** weak/one-off observations should not be prematurely promoted to durable memory.
4. **Model choice is config-driven within OpenRouter-backed remote calls.**
5. **Cost transparency:** extractor, reflector, run-once, and eval runs report LLM usage/cost and append ledger entries.

---

## 9) Known Undefined / Open Items

These are intentionally not finalized yet:

1. Exact scheduler runtime form (cron vs long-running daemon by default in production deployments).
2. Exact reflector trigger policy (time-based, size-based, or hybrid thresholds).
3. Canonical confidence scoring rubric for observations.
4. Retention policy for very old observation files.
5. How much tool-output content should be included/excluded in extraction context.
6. Canonical markdown schema versioning strategy for future evolution.
7. Canonical normalization policy for emergent remote extractor signal tags.

---

## 10) Spec Evolution Policy

This spec should track user-visible behavior only.

- If runtime behavior changes, update this document.
- If only internals change (same behavior), update design doc only.
- Unknowns can remain explicitly listed until settled.
