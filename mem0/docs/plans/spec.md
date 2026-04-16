# agent-session-mem0 — Specification

A CLI tool that ingests AI coding assistant session transcripts into a local vector store, extracting durable knowledge about the user (preferences, reasoning, decisions, expertise, relationships) and making it searchable via semantic query.

## Invocation

```
agent-session-mem0 [--verbose | --quiet] [--data-dir PATH] <command>
```

`--verbose` enables DEBUG-level logging to stderr. `--quiet` suppresses everything below ERROR. `--data-dir` overrides the storage directory, which defaults to `~/.local/share/agent-session-mem0`.

## Commands

### `add-session <path> [--user-id ID] [--force]`

Ingest a single session transcript. Parses the file, sends each conversation turn (with surrounding context) to an LLM for fact extraction, and stores the results in the vector store.

Accepts JSONL (Claude Code and Pi formats) and Markdown (weave/Obsidian format). Format is auto-detected. A `.md` suffix triggers markdown parsing; JSONL files are distinguished by inspecting the first line (`type: "session"` means Pi, otherwise Claude).

Content-hash deduplication prevents re-processing. A file with the same SHA-256 hash is silently skipped unless `--force` is passed. `--user-id` defaults to `"willi"`. Progress is displayed via a Rich progress bar on stderr showing session ID, turn count, elapsed/estimated time, and running counts of discovered memories and processed messages. Observations and insights are printed to stderr as they're extracted (blue `observation:` prefix, green `insight:` prefix). On completion a summary line reports turn count, agent type, session ID, and project name.

### `add-dir <directory> [--user-id ID] [--force] [--glob PATTERN]`

Batch-ingest all session files matching a glob pattern under a directory. Defaults to `**/agent sessions/*.md` (the Obsidian vault layout). Each file is processed identically to `add-session`. Progress is shown as a nested display: an outer bar tracking files (with ingested/skipped/failed counters) and an inner bar tracking the current file's turn-level progress. Files that fail are logged and skipped — processing continues with the remaining files. Memory and manifest connections are shared across files for efficiency.

### `query <text> [--user-id ID] [--limit N]`

Semantic search over stored facts. Displays two views: a ranked table sorted by similarity score, and a timeline grouping the same results into time buckets (Last hour, Today, Yesterday, This week, This month, N months ago). Each row shows the timestamp, project, fact text, and (in the ranked view) the similarity score. `--limit` defaults to 10.

### `list [--user-id ID]`

Show all stored facts in the timeline view. No filtering or ranking, just chronological grouping.

### `reset [--yes]`

Destroy all data: wipes the FAISS index directory and the manifest database. Prompts for confirmation unless `--yes` is given.

## Session Format Support

### Claude Code JSONL

One JSON object per line. Each object has a `type` field (`"user"` or `"assistant"`), a `message` payload, and optional `timestamp`/`cwd` fields.

User messages that are meta (`.isMeta`), list-typed content, or content starting with `<bash-`, `<local-command`, or `<task-notification` are filtered out so only genuine human input is kept. Assistant content blocks are either `text` (kept, unless the text is `"No response requested."`) or `tool_use` (tool name recorded).

### Pi JSONL

Similar structure but wrapped differently: messages live under `.message.role` / `.message.content[]`, and tool invocations use `toolCall` instead of `tool_use`. Format detected by `type: "session"` plus a `version` key on the first line.

### Weave Markdown

Obsidian-flavored markdown with YAML frontmatter (`agent`, `session_id`, `project`), a metrics table, and a `## Conversation` section using callout blocks. User turns are `> [!note] User HH:MM:SS` and assistant turns are `> [!quote] Assistant` (which may start with `tools: name1, name2`). If a `<!-- weave:summary:start -->` block exists, it is prepended as a synthetic first turn.

## Memory Extraction

Extraction operates in two passes to produce memories at different granularities.

### Pass 1: Per-Turn Observations

Each conversation turn is sent to the LLM with surrounding context: up to 16 prior user messages for topic continuity, and assistant responses for only the 4 most recent prior turns (assistant text is bulky; distant assistant output adds noise). The target turn always includes both user and assistant text.

The extraction prompt produces **observations**: self-contained statements that include reasoning when the conversation reveals it. "User chose Click over argparse because the tool needs many subcommands" rather than bare "User uses Click".

The prompt prioritizes durable, reusable knowledge and explicitly excludes ephemeral implementation details (specific code changes, file paths, function names, task progress — git history is authoritative for those).

**Primary categories** (always extract):
- Preferences and opinions — things to repeat in future sessions
- Corrections and rejections — things to avoid
- Skills and expertise level
- Beliefs and mental models — how the user thinks about problems
- Relationships between people, projects, companies, and tools
- Personal context — role, team, company

**Secondary categories** (extract when durable):
- Active projects and goals (the project itself, not today's task on it)
- Workflows and processes
- Technical decisions with reasoning

The LLM is instructed to use the preceding context window to connect dots across nearby turns. If the reason for a decision appeared 3 turns earlier, the observation should incorporate it.

### Pass 2: Session Distillation

After all turns in a session are processed, the collected pass 1 observations are sent to the LLM in a second pass. This pass asks: given these observations from one session, what are the most important durable things to remember about this user for future sessions?

The distillation pass serves three purposes:
1. Filters implementation details that leaked through pass 1
2. Promotes higher-order patterns (e.g., inferring "User works at Hex-Rays" from multiple IDA-related observations)
3. Connects observations from distant turns that pass 1 couldn't link (outside the context window)

Distilled insights are stored with `memory_type: "insight"` metadata, while pass 1 observations use `memory_type: "observation"`. Both are searchable via `query` — the distinction exists for future filtering and to avoid double-counting during analysis.

### Cross-Session Context

Before the distillation pass, the system queries the existing memory store for memories related to the current session (by project name and key terms from early turns). A selection of relevant prior memories is included as context for the distillation LLM, enabling cross-session pattern recognition: reinforcing recurring preferences, noticing evolving opinions, and connecting information that spans multiple sessions.

## Storage

The vector store is FAISS with cosine distance and 768-dimensional embeddings. The LLM runs locally via lmstudio, currently configured for Gemma 4 26B. Embeddings come from Nomic `text-embedding-nomic-embed-text-v1.5`, also through lmstudio. A SQLite manifest database sits alongside the FAISS directory, tracking `(content_hash, path, session_id, turns, indexed_at)` to prevent duplicate ingestion.

All persistent state lives under `--data-dir` (default `~/.local/share/agent-session-mem0`).

## Output Conventions

stdout is reserved for command output (tables, fact lists). stderr carries status spinners, logging, progress messages, and summary lines. Exit code 0 on success, non-zero on error.

## Decisions

LLM and embedding calls go to lmstudio on localhost. No cloud API keys are needed and no data leaves the machine. This is deliberate because session transcripts contain sensitive project context.

Deduplication is content-hash based rather than path-based. The same session file moved to a different location won't be re-indexed. Editing a session file (changing its hash) will allow re-indexing.

Frontmatter is parsed with a simple `key: value` line splitter to avoid a PyYAML dependency.

The entire implementation lives in `cli.py`. This is acceptable at the current ~850 lines; if it grows past ~1200, session parsing and rendering should be extracted into separate modules.

Observations embed reasoning alongside facts ("X because Y") rather than storing them separately ("X" + "Y is true"). Separated fragments lose their causal link — vector search has no join operation, so the reason would need to independently rank high enough to surface alongside the decision. Compound statements retrieve well for both narrow and broad queries because they share semantic surface area with multiple query angles. The cost is that a very narrow keyword query might score slightly lower against a compound embedding than a bare fact, but the practical query patterns (preferences, decisions, "why did the user...") are overwhelmingly broad.

The two-pass architecture exists because per-turn extraction and session-level synthesis are fundamentally different tasks. Per-turn extraction has access to conversational context and can capture nuance, but can't see the whole session. Session distillation can identify patterns across all turns but works from extracted observations rather than raw conversation. Running both and storing both gives the best retrieval coverage — an observation captures the specific moment, an insight captures the pattern.

Cross-session context is retrieved before distillation rather than before per-turn extraction. Per-turn extraction already has a large context window (16 user turns + 4 assistant turns) and adding prior memories would bloat it further. Distillation operates on a compact list of observations, so the additional context is proportionally small and highly valuable — it's the only point where information from different sessions can be connected.
