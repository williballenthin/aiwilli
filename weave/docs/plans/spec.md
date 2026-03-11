Weave specification

Status: draft
Last updated: 2026-03-11

1. Purpose

Weave monitors one IMAP inbox and routes unread emails to handler logic based on the recipient address. It also scrapes Google Calendar meeting notes and chat transcripts on a recurring schedule. It can also monitor a directory of AI agent session transcripts (Claude Code, Pi Agent), parse them, and produce session summary notes.

2. Invocation

Command:
- `weave <vault_root> [--poll-interval N] [--once] [--verbose] [--quiet] [--source TAG] [--agent-sessions DIR]`

Behavior:
- `--once` processes one unread batch plus one calendar scrape plus one agent session scan, runs one daily-note sync pass, then exits.
- default mode stays connected and loops with IMAP IDLE; a background maintenance thread runs immediately at startup and then every 5 minutes for calendar scraping, agent session scraping, and once-per-day daily-note sync.
- `<vault_root>` must exist.
- `--source TAG` sets the calendar source tag in front matter (default: `@hex-rays.com`).
- calendar scraping is always enabled.
- `--agent-sessions DIR` points to the directory containing agent session JSONL files. Can also be set via `WEAVE_AGENT_SESSIONS_DIR` env var. If not set, agent session scraping is disabled.

3. Required runtime environment

- `IMAP_HOST`
- `IMAP_USER`
- `IMAP_PASSWORD`
- `WEAVE_BASE_EMAIL` (base mailbox, e.g. `name@example.com`)
- `WEAVE_ALLOWED_SENDERS` (comma-separated list of email addresses allowed to send to any route)

For calendar scraping:
- Google OAuth token at `$XDG_CONFIG_HOME/wballenthin/weave/token.json` (created via `scripts/setup_google_credentials.py`)
- Google OAuth client credentials at `$XDG_CONFIG_HOME/wballenthin/weave/credentials.json`

For agent session scraping:
- `WEAVE_AGENT_SESSIONS_DIR` or `--agent-sessions` pointing to a directory with `claude/` and/or `pi/` subdirectories containing JSONL session files.

4. Routing behavior

Routing is partially hardcoded: route variants (`+vnote`, `+rm2`, `+todo`) and handler mappings are in code, but allowed senders come from the `WEAVE_ALLOWED_SENDERS` env var (shared across all routes).

4.1 Voice route
- to-address: `<WEAVE_BASE_EMAIL local-part>+vnote@<WEAVE_BASE_EMAIL domain>`
- allowed senders: from `WEAVE_ALLOWED_SENDERS`
- output root: `<vault_root>/sink/`

4.2 reMarkable route
- to-address: `<WEAVE_BASE_EMAIL local-part>+rm2@<WEAVE_BASE_EMAIL domain>`
- allowed senders: from `WEAVE_ALLOWED_SENDERS`
- output root: `<vault_root>/sink/`

4.3 TODO route
- to-address: `<WEAVE_BASE_EMAIL local-part>+todo@<WEAVE_BASE_EMAIL domain>`
- allowed senders: from `WEAVE_ALLOWED_SENDERS`
- output root: `<vault_root>/sink/`

5. Output behavior

Date directory format: all handlers use nested `YYYY/MM/DD` directories under the output root. Decision: switched from flat `YYYY-MM-DD` to nested `YYYY/MM/DD` to reduce clutter in the sink directory and align with calendar scraper output.

5.1 Voice handler output
- note path: `<output>/<YYYY>/<MM>/<DD>/<HHMM> - transcription.md`
- attachment path: `<output>/<YYYY>/<MM>/<DD>/_attachments/<HHMM> - <filename>`
- note contains YAML frontmatter, including `summary`, plus the email plain-text body.

5.2 reMarkable handler output
- saved pdf: `<output>/<YYYY>/<MM>/<DD>/_attachments/<HHMM> - <stem>.pdf`
- note path: `<output>/<YYYY>/<MM>/<DD>/<HHMM> - <stem>.md`
- note contains YAML frontmatter, including `summary`, and an embed link to the saved PDF.
- transcription is generated through the `llm` CLI against model `gemini/gemini-3-flash-preview`.
- on transcription failure, Weave still writes an error note and marks the message as seen.

5.3 TODO handler output
- note path: `<output>/<YYYY>/<MM>/<DD>/<HHMM> - <sanitized-subject>.md`
- attachment path: `<output>/<YYYY>/<MM>/<DD>/_attachments/<HHMM> - <filename>`
- subject is sanitized for filesystem safety (colons, quotes, slashes etc. replaced with dashes, trailing dashes stripped, max 100 chars).
- note contains YAML frontmatter, including `summary`, a `## <subject>` heading, the email plain-text body, and Obsidian embed links for any attachments.
- daily note line format: `- [ ] TODO: <subject> [[<vault-relative-note-path>]]` (wiki-link, not embed).

5.4 Calendar scraper output
- scrapes Google Calendar events from the past 7 days.
- for each event with Google Doc attachments, exports the doc as markdown.
- for each event with chat transcript attachments (text/plain ending in "- Chat"), downloads the raw content.
- note path: `<output>/<YYYY>/<MM>/<DD>/<HHMM> - <sanitized-event-name>.md`
- if multiple doc attachments and one is Gemini notes: `<HHMM> - <event-name> (Gemini).md`
- chat transcripts: `<HHMM> - <event-name> (chat).md`
- front matter includes: summary, source, type (meeting_notes/meeting_chat), calendar, event name, date, attended status, doc URL, event URL, attendees list.
- shared notes (title starts with "Notes - ") are section-extracted for the event date only.
- file-existence check serves as cache; existing files are not re-exported.
- events without doc or chat attachments are skipped.
- attendance is determined from the self-attendee's responseStatus; organizer-only events default to attended.

5.5 Daily note entries
- for each newly written sink markdown note (from any handler), Weave appends an entry line to the corresponding daily note.
- daily note date uses the event/email timestamp date.
- line format for notes: `- <type>: [[<vault-relative-note-path>]] - <summary> #weave`
- line format for TODOs: `- [ ] todo: [[<vault-relative-note-path>]] - <summary> #weave`
- entry types: `transcript` (voice), `handwriting` (reMarkable), `meeting notes` (calendar docs), `meeting chat` (calendar chats), `todo`, `agent session` (AI agent sessions).
- links use Obsidian wiki-link syntax `[[path]]` (not embed `![[path]]`) to avoid inline content expansion.
- each sink markdown note managed by Weave carries a frontmatter property `summary`.
- daily note generation reads `summary` from the note frontmatter first.
- if `summary` is empty and a summarizer is configured, Weave generates a one-sentence daily-index summary, writes it back into the note's `summary` frontmatter property, and uses that exact text in the daily note line.
- if summarization fails or no summarizer is configured, the summary is omitted from the daily note line and the note keeps an empty or missing `summary` value.
- existing notes without a `summary` property are backfilled the first time Weave needs a summary for them.
- daily note folder is loaded from `<vault_root>/.obsidian/daily-notes.json` key `folder`.
- if the daily-notes config file is missing/invalid or folder is empty, Weave uses `<vault_root>/` as daily note folder.
- managed entries are identified by matching the `[[link]]` destination and `#weave` tag, not by exact line match.
- if Weave writes a note whose managed line already exists, it replaces that managed line in place so the daily note tracks the note's current `summary` value.
- once per day, Weave also scans `YYYY-MM-DD.md` files in the configured daily-note folder and rewrites managed `#weave` lines from the linked note's current frontmatter `summary` value, without calling the summarizer again.
- if a managed daily-note line points at a missing/unreadable note, Weave leaves that line unchanged during sync.
- daily note file I/O is thread-safe (calendar thread and IMAP thread share the writer).

5.6 Agent session scraper output
- scans `claude/` and `pi/` subdirectories of the configured agent sessions directory for `.jsonl` files.
- subagent session files (under `*/subagents/`) are skipped.
- parses both Claude Code and Pi Agent JSONL formats, auto-detecting by first line.
- session identity comes from the harness session ID: Claude usually uses the filename stem; Pi usually uses the session UUID from the timestamp-prefixed filename. Parsed JSONL data can also supply the session ID.
- for each session with at least one user turn, produces a markdown note with:
  - YAML front matter: type (agent_session), summary, agent, project, session_id, session_sha256, timestamps, duration, models, token counts, cost (pi only), user turn count, tool call count.
  - an LLM-generated structured summary section (goal, decisions, work completed, topics).
  - metrics table.
  - full conversation with user messages and user-directed assistant responses.
- note path: `<output>/<YYYY>/<MM>/<DD>/<session-id>.md`
- date directory is based on session start time.
- sync state is tracked in a JSON manifest at `$XDG_CACHE_HOME/wballethin/weave/agent-session-manifest.json` (falling back to `~/.cache/...`). Missing or malformed manifests are treated as cache misses and are regenerated on the next scan.
- on each scan, agent session files modified within the last 7 days are treated as mutable and are checked against the manifest. Older files are treated as immutable once they have a manifest entry and an existing sink note.
- the manifest stores per-source-file session ID, SHA-256, sink path, and source mtime for incremental sync.
- if a mutable file's SHA-256 changes, Weave rewrites the sink note and updates the managed daily-note line.
- each agent-session scan emits a JSON sync report to stdout summarizing scanned, imported, updated, unchanged, immutable-skipped, empty-skipped, and failed sessions.
- daily note entry type: `agent session`.
- agent session note body summary and frontmatter/daily-note summary are separate outputs with separate prompts.

6. Message visibility behavior

- a successfully handled routed message is marked `\\Seen` after sink-note writing and daily-note entry updates succeed.
- unrouted messages are left unread.
- routed messages with disallowed senders are left unread.
- reMarkable-routed messages without PDF attachments are left unread.
- duplicate entry lines are not appended.

7. Future extension contract

New email workflows should be added as new handler keys plus new hardcoded routes.
