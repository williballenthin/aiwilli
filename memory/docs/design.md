# Global Observational Memory System — Technical Design

Status: Draft (v0.4 remote-only eval capable)  
Last updated: 2026-02-21

This document describes the current implemented architecture in `memory/`.

---

## 1) Current implementation decisions

1. Python 3.12+
2. Package name: `memory_claw`; CLI: `memory-claw`
3. Memory root default: `~/.memory-claw` (override via `--memory-root` or `MEMORY_CLAW_ROOT`)
4. Data artifacts are markdown files + git history
5. Runtime state is SQLite (`state.db`)
6. Extraction and reflection are remote-LLM-only stages
7. OpenRouter-compatible HTTP client implemented directly (stdlib `urllib`) for now

---

## 2) Implemented code layout

```text
memory/
  pyproject.toml
  src/memory_claw/
    cli/app.py
    config/{models.py,loader.py}
    adapters/{base.py,pi_adapter.py,claude_adapter.py}
    domain/{messages.py,observations.py,memory_doc.py}
    store/{db.py,schema.sql,repositories.py}
    pipeline/{watcher.py,extractor_runner.py,reflector.py,scheduler.py}
    llm/{client.py,extractor_agents.py,reflector_agent.py}
    io/{fs_paths.py,markdown_writer.py,git_ops.py,cost_ledger.py}
    eval/harness.py
    prompts/loader.py
```

---

## 3) Configuration model

`config/models.py` provides typed config:

- `sources`: transcript roots (`pi`, `claude`)
- `extractors`: strategy/model/prompt configuration
  - context flags include `include_global_memory`, `include_project_docs`, `project_docs_max_chars`
- `llm`:
  - connection info (`provider`, `base_url`, `api_key_env`)
  - operational limits (`timeout_seconds`, `max_retries`)
  - cost guards (`max_run_cost_usd`, `max_run_calls`)
- `reflector`: model/prompt/lookback

---

## 4) Watcher stage

`pipeline/watcher.py`

- discovers sessions via adapter interface
- ingests new transcript lines since cursor
- normalizes messages and upserts into DB
- advances `sessions.last_ingested_line`

Adapters:

- Pi (`adapters/pi_adapter.py`): `type=message`, maps `toolResult -> tool`, and keys session identity by transcript relative path (avoids filename-suffix collisions)
- Claude (`adapters/claude_adapter.py`): includes top-level `type in {user, assistant}`, skips index files and all `subagents/` transcripts, and uses `sessions-index.json` metadata (when present) to attach `projectPath` as cwd/project context

---

## 5) Extractor stage

`pipeline/extractor_runner.py`

- reads enabled extractors
- computes per-session progress via `extractor_progress` cursor
- builds chunks (`pairwise`, `sliding_window`)
  - pairwise mode scans session history and emits assistant→user pairs anchored on *new user lines* (`line_no > cursor`), allowing tool messages between assistant and user
  - pairwise mode also emits the first user turn as a single-message chunk when no assistant precedes it (captures initial thread goal)
  - this avoids dropping pairwise signals when assistant/user turns cross run boundaries or include interleaved tool output
- builds per-chunk context bundle:
  - transcript chunk
  - optional global memory snapshot
  - project docs context (`README*`, `AGENTS.md`, `CLAUDE.md`) via `io/project_context.py`
  - rolling prior observations for that session (latest ~5)
- processes chunks via `llm/extractor_agents.py`
  - remote line-based extraction (`- <importance> [signal_type] summary | why: reason` per line)
  - importance markers: `🔴`/`🟡`/`🟢`
  - prompt assembly now uses a fixed ordered scaffold: role, task, what-is-coming list, background, good/bad few-shots, project README, agent context files, prior observations, repeated task reminder, transcript input, repeated task reminder
  - project docs context is split into README vs agent-context subsections when possible
  - strict parser converts lines into structured `ObservationItem`s (`importance`, `signal_type`, `summary`, `why`)
  - malformed output triggers full re-inference (bounded attempts), no tolerant parsing
  - no heuristic fallback path
  - prompt file content is treated as actor-specific override guidance, layered into the scaffold
- appends observations markdown by extractor/day
- commits observation changes
- applies cursor updates only after observation writes succeed (staged cursor updates prevent data loss on write failure)
- advances extractor cursor only to processed line boundary (supports partial progress)

Extractor run result also reports:

- `llm_calls`
- token counts
- `llm_cost_usd`
- `llm_budget_hit`

---

## 6) Reflector stage

`pipeline/reflector.py`

- loads current `global_memory.md`
- gathers recent links from primary extractor collections
- gathers recent primary observation markdown snippets (bounded char budget) for reflector input context
- invokes `llm/reflector_agent.py`:
  - remote markdown response path (full document text, no JSON required)
  - prompt assembly uses the same fixed ordered actor scaffold (including repeated task reminders and explicit input-data section)
  - reflector input-data section includes current memory + recent links + recent observation contents
  - reflector prompt treats observer importance and why-rationales as qualitative salience/context (without hard-coded count thresholds)
  - strict format validation (`# Global Memory` first, required sections present, no code fences/JSON)
  - malformed output triggers full re-inference (bounded attempts), no tolerant parsing
  - no local fallback path
- atomic write to `global_memory.md`
- commits reflector update
- updates `reflector_state`
- reports LLM usage/cost metrics

---

## 7) LLM client + cost accounting

`llm/client.py`:

- OpenRouter chat-completions POST
- parses usage block from API responses (`prompt_tokens`, `completion_tokens`, `total_tokens`, `cost`)
- accumulates in-process metrics (`LLMMetrics`)
- enforces run budget checks (`max_run_cost_usd`, `max_run_calls`)

`io/cost_ledger.py`:

- appends per-command usage entries to `<memory_root>/costs.jsonl`
- summarizes cumulative cost/tokens/calls

CLI commands append usage entries for:

- `extractors run`
- `reflector run`
- `run once` (combined stage cost)
- `eval run`

`memory-claw status` displays cumulative totals.

`memory-claw run once` executes watcher, then extractors, and only runs reflector if extractor stage completed without errors.

---

## 8) Evaluation harness

`eval/harness.py` powers `memory-claw eval run`:

- runs watcher ingestion first so evaluation uses current transcript state,
- samples transcript chunks from ingested sessions (stratified by source),
- evaluates observer cases in parallel across sessions (configurable worker threads) while preserving per-session prior-observation continuity,
- merges per-session temporary results into deterministic case-id order,
- reuses live observer/reflector actor logic against sampled inputs,
- captures prompt/response attempts via a tracing LLM client wrapper,
- writes review artifacts under `eval/runs/<run-id>/`:
  - `observer_cases.jsonl`
  - `reflector_cases.jsonl`
  - `report.md`

Claude `subagents/` transcripts are excluded upstream in adapter discovery, so eval sampling remains user-interaction-only.

---

## 9) Known quality gaps (current)

1. Extractor signal taxonomy is not normalized in remote mode (model may emit ad-hoc signal labels).
2. Reflector remote output quality still depends heavily on prompt quality even with stricter scaffolding/validation.
3. Regression tests cover critical ingest/pairwise/cursor/remote-only failure paths, but broader fixture and golden-output coverage is still limited.
4. Project-doc context discovery is best-effort from cwd/index metadata and can miss repos when cwd is absent/unresolvable.

---

## 10) Next engineering steps

1. Add strict signal-type normalization layer and confidence rubric.
2. Add test fixtures for Pi and Claude transcripts with golden markdown outputs.
3. Improve reflector prompt + post-validation schema checks.
4. Add richer commit messages with source/session summaries.
5. Add optional per-model cost breakdown in `costs.jsonl`.
6. Add persistence of prior-observation context across runs (not only within current run loop).
