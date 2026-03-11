Agent Session Format Research

Date: 2026-03-11
Source: /db/containers/syncthing/Sync/agent-sessions/

1. Overview

Two agent harnesses produce session transcripts: Claude Code and Pi Agent.
Both store JSONL files (one JSON object per line) organized by project directory.

Corpus size:
- Claude: 84 project dirs, 2413 JSONL files, ~663MB total
- Pi: 42 project dirs, 284 JSONL files, ~56MB total
- Individual files range from a few KB to ~12MB

2. Directory structure

2.1 Claude Code

    agent-sessions/claude/<encoded-path>/<session-uuid>.jsonl
    agent-sessions/claude/<encoded-path>/<session-uuid>/subagents/<agent-id>.jsonl

Path encoding: absolute path with `/` replaced by `-`, prefixed with `-`.
Example: `/Users/user/code/aiwilli/weave` -> `-Users-user-code-aiwilli-weave`

Some sessions have a subdirectory with the same UUID containing `subagents/` with
additional JSONL files for spawned subagents.

Session IDs are UUIDs: `1a16d739-fa56-4bb7-a462-f2496413208f`

2.2 Pi Agent

    agent-sessions/pi/<encoded-path>/<timestamp>_<session-uuid>.jsonl

Path encoding: absolute path with `/` replaced by `-`, wrapped in `--`.
Example: `/Users/user/code/aiwilli/weave` -> `--Users-user-code-aiwilli-weave--`

Session files are named with an ISO timestamp prefix:
`2026-03-03T16-00-24-231Z_756994f1-6615-471c-96f1-907adc5960a7.jsonl`

This means the Pi filename itself encodes the session start time,
while Claude sessions require parsing internal timestamps.

3. Claude Code JSONL format

3.1 Line types (by `type` field)

| type                  | description                                       | frequency |
|-----------------------|---------------------------------------------------|-----------|
| user                  | user message (human, tool result, or meta/system)  | high      |
| assistant             | assistant response (text, tool_use, thinking)       | high      |
| progress              | hook progress events (PostToolUse etc.)              | high      |
| file-history-snapshot | git/file backup snapshots                           | medium    |
| queue-operation       | task queue enqueue/remove events                    | low       |
| system                | system reminders, turn duration metrics              | low       |

Example counts from one 451-line session:
progress: 184, assistant: 111, user: 95, file-history-snapshot: 43, queue-operation: 14, system: 4

3.2 Common fields on user/assistant records

- `parentUuid`: links to previous message, forms a chain
- `isSidechain`: boolean, indicates branched conversations
- `cwd`: working directory (the original project path, not encoded)
- `sessionId`: UUID matching the filename
- `version`: Claude Code version (e.g. "2.1.50")
- `gitBranch`: current git branch
- `slug`: auto-generated session slug (e.g. "idempotent-stargazing-mountain")
- `uuid`: this record's unique ID
- `timestamp`: ISO 8601 timestamp
- `type`: "user" | "assistant" | etc.
- `message`: the actual message payload

3.3 Message payload structure

User messages (`message.role == "user"`):
- `content` is either a string (human text, bash output, meta tags) or a list
  (tool results with `type: "tool_result"` objects)
- `isMeta: true` marks system-injected messages (local command caveats)

Assistant messages (`message.role == "assistant"`):
- `message.model`: model ID (e.g. "claude-opus-4-6", "<synthetic>" for no-response)
- `message.id`: API message ID (e.g. "msg_01LEUQszgvhABhEU6WLeRWkg")
- `message.content`: array of content blocks
- `message.usage`: token usage per API call
- `message.stop_reason`: null during streaming, "end_turn" at completion

Content block types in assistant messages:
- `thinking`: extended thinking (has `thinking` text and `signature`)
- `text`: user-facing text response
- `tool_use`: tool invocation (has `name`, `input`, `id`)

3.4 Token usage (per assistant record)

    {
      "input_tokens": 3,
      "cache_creation_input_tokens": 11185,
      "cache_read_input_tokens": 10419,
      "output_tokens": 11,
      "service_tier": "standard",
      "cache_creation": {
        "ephemeral_5m_input_tokens": 0,
        "ephemeral_1h_input_tokens": 11185
      }
    }

IMPORTANT: Claude Code emits multiple assistant records per API call (streaming).
The same API call ID (`message.id`) appears on multiple JSONL lines, each with
incremental content blocks. The `usage` object changes across records — specifically
`output_tokens` increases monotonically as more content is streamed. `input_tokens`
and cache tokens stay constant. To get accurate totals, take the LAST record for
each unique `message.id` (it has the final output_tokens count).

Verified: output_tokens are always ascending or equal across records sharing a msg_id.

No cost data is provided directly. Cost must be computed from token counts
using known pricing for the model.

3.5 System records

`type: "system"` with `subtype: "turn_duration"` carries `durationMs` field,
measuring wall-clock time for a single turn.

3.6 Identifying user-typed messages vs system messages

Three categories of `type: "user"` records:
1. Human-typed: `isMeta` is absent/false, `content` is a plain string, does not
   start with `<bash-` or `<local-command`
2. Tool results: `content` is a list containing `type: "tool_result"` objects
3. Meta/system: `isMeta: true`, or content starts with `<bash-input>`, `<bash-stdout>`,
   `<bash-stderr>`, or `<local-command-caveat>`

3.7 Identifying user-directed assistant messages

The assistant produces multiple JSONL records per turn:
- thinking blocks (internal reasoning, not user-facing)
- tool_use blocks (tool invocations, not user-facing)
- text blocks (user-facing responses)

User-directed assistant messages are those with `type: "text"` content blocks.
The pattern is: after a human user message, the assistant may do thinking + tool calls,
then eventually emits text blocks addressed to the user.

The last assistant `text` block(s) before the next human user message represent
the assistant's final response to the user for that turn.

Heuristic: walk the conversation in order, collect assistant text blocks between
human user messages. These are the user-directed responses for that turn.

4. Pi Agent JSONL format

4.1 Line types (by `type` field)

| type                   | description                          | frequency |
|------------------------|--------------------------------------|-----------|
| message                | user, assistant, or toolResult       | high      |
| session                | session header (first line)          | 1         |
| model_change           | model switch event                   | low       |
| thinking_level_change  | thinking level adjustment            | low       |

Example counts from one 50-line session:
message: 47, session: 1, model_change: 1, thinking_level_change: 1

4.2 Tree structure

Pi sessions are a tree, not a flat list. Each entry has `id` and `parentId`.
To reconstruct a linear conversation, start from the leaf and walk `parentId`
back to root, then reverse. Pi's `buildSessionContext()` does exactly this.

For most sessions (no branching), the `parentId` chain is sequential and
equivalent to reading lines in order.

4.3 Session header

First line, `type: "session"`:

    {
      "type": "session",
      "version": 3,
      "id": "756994f1-6615-471c-96f1-907adc5960a7",
      "timestamp": "2026-03-03T16:00:24.231Z",
      "cwd": "/Users/user/code/aiwilli/weave"
    }

4.4 Model change

    {
      "type": "model_change",
      "provider": "openai-codex",
      "modelId": "gpt-5.3-codex"
    }

This is useful: it tells us which provider/model was used.

4.5 Message records

`type: "message"` with `message.role` being:
- `"user"`: human-typed messages
- `"assistant"`: assistant responses
- `"toolResult"`: tool execution results

User messages: `message.content` is a list of `{type: "text", text: "..."}` blocks.
Much simpler than Claude - no meta/bash injection messages. All user messages
in the JSONL are actual human input.

Assistant messages: `message.content` contains:
- `thinking`: internal reasoning (has `thinkingSignature` for encrypted reasoning)
- `text`: user-facing text
- `toolCall`: tool invocation (has `name`/`toolName`, `arguments`, `id`)

Content type patterns observed:
- `['thinking']` - thinking only, followed by tool results
- `['thinking', 'text']` - thinking + user-facing text (final response to user)
- `['thinking', 'toolCall']` - thinking + tool call (not observed but possible)

Key insight: Pi assistant messages with a `text` block are user-directed.
These only appear when the assistant is done with tool calls and ready to
address the user. This is cleaner to detect than Claude's format.

4.6 Token usage and cost (per assistant message)

    {
      "input": 3112,
      "output": 244,
      "cacheRead": 0,
      "cacheWrite": 0,
      "totalTokens": 3356,
      "cost": {
        "input": 0.005446,
        "output": 0.003416,
        "cacheRead": 0,
        "cacheWrite": 0,
        "total": 0.008862
      }
    }

Pi provides cost data directly. No need to compute from pricing tables.
Usage is on the `message.usage` field of assistant messages.

4.7 Tool call structure

    {
      "type": "toolCall",
      "id": "call_ABdLyG27SH1ZKnkrXOpjaEo1|...",
      "name": "bash",
      "arguments": {"command": "ls -la"},
      "partialJson": "{\"command\":\"ls -la\"}"
    }

The `name` field gives the tool name. `arguments` has structured input.

5. Extractable metrics (both formats)

5.1 Session-level metadata
- Session ID (from filename or session header)
- Project path (from directory name or cwd field)
- Start timestamp (first record timestamp)
- End timestamp (last record timestamp)
- Duration (end - start)
- Model(s) used
- Git branch
- Claude Code version (claude only)
- Provider (pi only, e.g. "openai-codex")

5.2 Token metrics
- Total input tokens
- Total output tokens
- Cache read/creation tokens (claude) or cache read/write (pi)
- Total cost (pi: direct; claude: must compute from pricing)

For Claude, deduplicate by `message.id` to avoid counting streaming duplicates.

5.3 Message counts
- Human user messages
- User-directed assistant text messages
- Tool calls (count of tool_use/toolCall blocks)
- Thinking blocks
- Total JSONL lines

5.4 Content extraction
- All human user message texts (verbatim)
- All user-directed assistant text responses (verbatim)
- Tool names and counts (what tools were used, how often)

6. Differences summary

| Aspect              | Claude Code                        | Pi Agent                      |
|----------------------|------------------------------------|-------------------------------|
| Path encoding        | `-` prefix, `/` -> `-`            | `--` wrap, `/` -> `-`         |
| Session ID in name   | UUID only                          | timestamp_UUID                |
| Structure            | flat chain (parentUuid)            | tree (id/parentId)            |
| Session header       | no dedicated header line           | `type: "session"` first line  |
| User msg complexity  | mixed (human, tool, meta, bash)    | simple (only human messages)  |
| Assistant streaming  | multiple records per API call      | one record per turn           |
| Token dedup needed   | yes (last record per message.id)   | no                            |
| Cost data            | not provided                       | provided per message          |
| Subagents            | separate JSONL files in subdir     | not observed                  |
| Model info           | on each assistant message           | model_change entry            |
| Thinking             | text in `thinking` field           | encrypted in some providers   |

7. Approach for user-directed message extraction

7.1 Claude Code

Walk JSONL in order. Maintain state:
- When encountering a human user message, emit the previous turn's collected
  assistant text blocks as "user-directed responses" for the previous turn.
- Collect assistant text blocks between human user messages.
- Filter: skip `isMeta`, skip tool results, skip bash-tagged content.

7.2 Pi Agent

Simpler: any assistant message with a `text` content block is user-directed.
These only appear when the assistant is responding to the user (not during
intermediate tool-call chains).

8. Implementation considerations

8.1 File sizes
Largest files are ~12MB. All fit in memory. No streaming parser needed,
but line-by-line processing is still efficient.

8.2 Claude streaming dedup
Multiple JSONL lines share the same `message.id`. For token counting,
group by `message.id` and take the usage from any one record (they're
identical). For content extraction, accumulate content blocks across all
records with the same `message.id`.

8.3 Subagent handling
Claude subagent sessions are in `<session-uuid>/subagents/`. These are
full sessions in their own right. For initial implementation, we could:
- Ignore subagents (simplest)
- Count them and note their existence
- Recursively process them and roll up metrics

Recommendation: count subagents and note tool calls dispatched to them,
but don't recursively parse for the initial version.

8.4 Project name extraction
From the encoded directory name, we can recover the project name:
- Claude: strip leading `-`, split on `-`, take last component(s)
- Pi: strip `--` wrapping, split on `-`, take last component(s)
- Or use the `cwd` field from inside the JSONL (more reliable)

8.5 Timestamp handling
All timestamps are ISO 8601 with timezone (UTC `Z` suffix).
Python's `datetime.fromisoformat()` handles these directly.

9. Planned output

For each session, produce:
- A summary markdown file in the sink directory
- A daily note entry linking to the summary

The summary should include:
- Session metadata (project, model, branch, duration, timestamps)
- Token usage and cost
- Message counts (human messages, assistant responses, tool calls)
- Verbatim human user messages
- Verbatim user-directed assistant text responses
- (Future) LLM-generated summary of goals, decisions, work done
