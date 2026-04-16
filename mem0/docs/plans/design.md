# agent-session-mem0 — Design

## Architecture

The tool is a single-module Click CLI (`src/agent_session_mem0/cli.py`) with four logical layers stacked in one file:

```
CLI commands (click group + 5 subcommands)
    │
    ├── Session parsing (3 format parsers → SessionData)
    │
    ├── Pass 1: Per-turn observation extraction
    │     └── Context building (sliding window over turns → message list)
    │     └── mem0.add() → LLM extracts observations → FAISS stores embeddings
    │
    ├── Pass 2: Session distillation
    │     └── Cross-session context retrieval (query existing store)
    │     └── Direct LLM call → distilled insights
    │     └── Store insights via mem0.add()
    │
    ├── Storage (mem0 Memory + FAISS + SQLite manifest)
    │
    └── Rendering (Rich tables, time-bucketed timeline)
```

## Data Flow

### Ingestion (`_ingest_file`)

Both `add-session` (single file) and `add-dir` (batch) delegate to `_ingest_file()`, which owns the full ingestion pipeline for one file:

```
file on disk
  → content hash (SHA-256)
  → manifest check (SQLite: skip if seen)
  → format detection (.md vs .jsonl, then Claude vs Pi)
  → parse into SessionData (agent, session_id, project, list[SessionTurn])
  → Pass 1: per-turn observation extraction
      → for each non-empty turn:
          → build_contextual_messages (sliding window of prior context)
          → mem0.add(messages, user_id, metadata={..., memory_type: "observation"})
            → LLM extracts observations via TURN_EXTRACTION_PROMPT
            → embedder produces vectors → FAISS stores embeddings
          → collect extracted observations from m.add() result
          → print each observation to stderr (blue prefix)
  → Cross-session context retrieval
      → query existing store with project name + key terms from early turns
      → select top N relevant prior memories as context
  → Pass 2: session distillation
      → send all pass 1 observations + cross-session context to LLM
        (direct HTTP call to lmstudio, not via mem0)
      → LLM produces distilled insights via SESSION_DISTILLATION_PROMPT
      → for each insight: mem0.add(insight, infer=False) with memory_type: "insight"
      → print each insight to stderr (green prefix)
  → record in manifest
  → return IngestionResult
```

### Batch ingestion (`add-dir`)

`add-dir` globs session files under a directory (default pattern `**/agent sessions/*.md`), creates a single Memory instance and manifest connection, then calls `_ingest_file` for each file within a shared Rich Progress context. The Progress has two tasks: an outer file-level bar and an inner detail bar that `_ingest_file` resets per-pass. Failed files are caught, logged, and skipped.

### Query (`query`)

```
query text → mem0.search(text, user_id, limit) → FAISS cosine similarity
  → ranked result table (stdout)
  → timeline view grouped by time bucket (stdout)
```

## Key Data Structures

`SessionTurn` represents one user prompt and the assistant's response. It holds `user_text`, a list of `assistant_texts` (multiple text blocks per response), a list of `tool_names` invoked during the turn, and an optional `timestamp`.

`SessionData` wraps a parsed session file: the `agent` string ("claude", "pi", or from frontmatter), `session_id`, `project` (derived from cwd for JSONL or frontmatter for MD), and the list of `SessionTurn`s.

`IngestionResult` is the return type from `_ingest_file`: status (`"ingested"`, `"skipped"`, or `"empty"`), session metadata, and counts of turns/observations/insights processed. Both `add-session` and `add-dir` use it to drive their summary output.

## Session Parsing

Three parsers produce the same `SessionData` output:

| Format | Detection | Parser | Notes |
|--------|-----------|--------|-------|
| Claude JSONL | Default for `.jsonl` | `_build_claude_turns` | Filters meta/system messages, extracts `tool_use` blocks |
| Pi JSONL | First line has `type: "session"` + `version` | `_build_pi_turns` | Uses `toolCall` instead of `tool_use` |
| Weave MD | `.md` suffix | `parse_md_session` | Obsidian callouts, YAML frontmatter, optional summary block |

The Claude and Pi parsers share the same state-machine pattern: accumulate user text, then collect assistant blocks until the next user message triggers a flush. The MD parser does the same but over callout-delimited sections.

## Contextual Message Building

`build_contextual_messages(turns, target_idx)` constructs the message list sent to mem0 for observation extraction. The design balances context quality against token cost.

User messages from up to 16 prior turns are included because topic continuity matters for extraction quality. Assistant messages are included for only the 4 turns immediately before the target, since assistant text is verbose and distant assistant output is mostly noise. The target turn always includes both user and assistant text. This produces a conversation-shaped message list that the extraction LLM can reason over naturally.

## Session Distillation

After pass 1 completes, the system runs a distillation pass. This is a direct HTTP call to lmstudio (`POST /v1/chat/completions`) rather than going through mem0, because mem0's `add()` always runs the per-turn extraction prompt — we need a different prompt for distillation.

The distillation input is:
1. All observations collected from pass 1 (as a formatted list)
2. Cross-session context: top-N relevant memories from the existing store, retrieved by querying with the session's project name and key terms extracted from early turns

The `SESSION_DISTILLATION_PROMPT` asks the LLM to identify the most important durable knowledge from the session: user-level patterns, preferences, expertise, relationships. It explicitly asks the LLM to filter out implementation details and promote higher-order inferences.

The distilled insights are stored back into mem0 via `m.add(insight, user_id=user_id, metadata=metadata, infer=False)`. The `infer=False` flag bypasses LLM extraction and embeds the string directly into the vector store, so insights are stored exactly as the distillation LLM produced them. Each insight gets `memory_type: "insight"` in its metadata.

## Cross-Session Context Retrieval

`_retrieve_session_context(m, user_id, session)` queries the existing FAISS store before distillation. It builds queries from the session's project name and a sample of user messages from early turns, retrieves the top results, deduplicates, and returns them as a list of prior memory strings. This context is included in the distillation prompt so the LLM can connect patterns across sessions — reinforcing recurring preferences or noting when the current session contradicts prior observations.

## Storage Layout

Everything under `--data-dir` (default `~/.local/share/agent-session-mem0`):

```
~/.local/share/agent-session-mem0/
├── manifest.db              # SQLite: indexed_files(content_hash, path, session_id, turns, indexed_at)
└── faiss/
    ├── sessions.faiss       # FAISS index (cosine, 768-dim)
    └── sessions.pkl         # Embedding metadata
```

The manifest sits at the same level as the FAISS directory. Its path is derived from the FAISS config path (`faiss_path.parent / "manifest.db"`).

## mem0 Configuration

Built by `_build_config()`. The LLM is lmstudio with Gemma 4 26B, using JSON schema response format and 4000 max tokens. The embedder is lmstudio with Nomic `text-embedding-nomic-embed-text-v1.5` at 768 dimensions. The vector store is FAISS with cosine distance, collection name `"sessions"`.

Two prompts drive extraction:

`TURN_EXTRACTION_PROMPT` (used by mem0 via `custom_fact_extraction_prompt` config) — produces per-turn observations. Prioritizes durable knowledge (preferences, reasoning, skills, relationships) over implementation details. Instructs the LLM to include reasoning ("because...") when the conversation reveals it, and to synthesize across the context window. Returns `{"facts": [...]}` (key name kept for mem0 compatibility).

`SESSION_DISTILLATION_PROMPT` (used directly via lmstudio HTTP call) — takes the collected observations from a session plus cross-session context, and produces distilled insights. Filters implementation noise, promotes higher-order patterns, connects dots across the full session. Returns `{"insights": [...]}`.

## Rendering

Two display modes, both using Rich.

`_print_ranked` produces a score-sorted table for query results with columns for score, timestamp, project, and fact. `_print_timeline` groups entries into time buckets (Last hour through N months ago) using `_time_bucket`. Each bucket is a Rich table with timestamp, project, session (truncated to 8 chars), and fact. Buckets are ordered by recency, with well-known names first and overflow month-buckets appended.

## Deduplication

Content-hash based (SHA-256 of the raw file bytes). The manifest stores the hash as primary key. On `add-session`, the hash is computed before parsing; if the hash exists in the manifest and `--force` is not set, the file is skipped with a message to stderr. After successful ingestion, the hash is recorded.

Same content at a different path is skipped. Modified content at the same path gets re-indexed (new hash). The `--force` flag bypasses the check entirely, using `INSERT OR REPLACE` to update the manifest row.
