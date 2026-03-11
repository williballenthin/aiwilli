Weave specification

Status: draft
Last updated: 2026-03-11

1. Purpose

Weave monitors one IMAP inbox and routes unread emails to handler logic based on the recipient address. It also scrapes Google Calendar meeting notes and chat transcripts on a recurring schedule. It can also monitor a directory of AI agent session transcripts (Claude Code, Pi Agent), parse them, and produce session summary notes.

2. Invocation

Command:
- `weave <vault_root> [--poll-interval N] [--once] [--verbose] [--quiet] [--source TAG] [--no-calendar] [--agent-sessions DIR]`

Behavior:
- `--once` processes one unread batch plus one calendar scrape plus one agent session scan, then exits.
- default mode stays connected and loops with IMAP IDLE; calendar scraper and agent session scraper run in a background thread every 5 minutes.
- `<vault_root>` must exist.
- `--source TAG` sets the calendar source tag in front matter (default: `@hex-rays.com`).
- `--no-calendar` disables the calendar scraper entirely.
- `--agent-sessions DIR` points to the directory containing agent session JSONL files. Can also be set via `WEAVE_AGENT_SESSIONS_DIR` env var. If not set, agent session scraping is disabled.

3. Required runtime environment

- `IMAP_HOST`
- `IMAP_USER`
- `IMAP_PASSWORD`
- `WEAVE_BASE_EMAIL` (base mailbox, e.g. `name@example.com`)
- `WEAVE_ALLOWED_SENDERS` (comma-separated list of email addresses allowed to send to any route)

For calendar scraping (unless `--no-calendar`):
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
- note contains frontmatter and the email plain-text body.

5.2 reMarkable handler output
- saved pdf: `<output>/<YYYY>/<MM>/<DD>/_attachments/<HHMM> - <stem>.pdf`
- note path: `<output>/<YYYY>/<MM>/<DD>/<HHMM> - <stem>.md`
- note contains embed link to saved PDF.
- transcription is generated through the `llm` CLI against model `gemini/gemini-3-flash-preview`.
- on transcription failure, Weave still writes an error note and marks the message as seen.

5.3 TODO handler output
- note path: `<output>/<YYYY>/<MM>/<DD>/<HHMM> - <sanitized-subject>.md`
- attachment path: `<output>/<YYYY>/<MM>/<DD>/_attachments/<HHMM> - <filename>`
- subject is sanitized for filesystem safety (colons, quotes, slashes etc. replaced with dashes, trailing dashes stripped, max 100 chars).
- note contains YAML frontmatter, a `## <subject>` heading, the email plain-text body, and Obsidian embed links for any attachments.
- daily note line format: `- [ ] TODO: <subject> [[<vault-relative-note-path>]]` (wiki-link, not embed).

5.4 Calendar scraper output
- scrapes Google Calendar events from the past 7 days.
- for each event with Google Doc attachments, exports the doc as markdown.
- for each event with chat transcript attachments (text/plain ending in "- Chat"), downloads the raw content.
- note path: `<output>/<YYYY>/<MM>/<DD>/<HHMM> - <sanitized-event-name>.md`
- if multiple doc attachments and one is Gemini notes: `<HHMM> - <event-name> (Gemini).md`
- chat transcripts: `<HHMM> - <event-name> (chat).md`
- front matter includes: source, type (meeting_notes/meeting_chat), calendar, event name, date, attended status, doc URL, event URL, attendees list.
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
- each line ends with `#weave` tag to enable future regeneration of managed lines.
- summary is generated by LLM (same model as transcription) with a prompt requesting one sentence for a daily index overview. Decision: changed from three sentences to one sentence — three was too verbose for a daily index line.
- if summarization fails or no summarizer is configured, the summary is omitted and the line still contains type, link, and tag.
- daily note folder is loaded from `<vault_root>/.obsidian/daily-notes.json` key `folder`.
- if the daily-notes config file is missing/invalid or folder is empty, Weave uses `<vault_root>/` as daily note folder.
- duplicate entries are detected by matching the `[[link]]` destination and `#weave` tag, not by exact line match. This means a note that was already linked won't be re-summarized or re-appended even if the LLM would produce a different summary.
- daily note file I/O is thread-safe (calendar thread and IMAP thread share the writer).

5.6 Agent session scraper output
- scans `claude/` and `pi/` subdirectories of the configured agent sessions directory for `.jsonl` files.
- subagent session files (under `*/subagents/`) are skipped.
- parses both Claude Code and Pi Agent JSONL formats, auto-detecting by first line.
- for each session with at least one user turn, produces a markdown note with:
  - YAML front matter: type (agent_session), agent, project, session_id, timestamps, duration, models, token counts, cost (pi only), user turn count, tool call count.
  - LLM-generated structured summary (goal, decisions, work completed, topics).
  - metrics table.
  - full conversation with user messages and user-directed assistant responses.
- note path: `<output>/<YYYY>/<MM>/<DD>/<HHMM> - <agent> - <project> (<session-id-prefix>).md`
- date directory is based on session start time.
- file-existence check serves as cache; existing files are not re-processed.
- daily note entry type: `agent session`.
- for daily note one-liner, uses a dedicated one-sentence prompt focused on what was accomplished.

6. Message visibility behavior

- a successfully handled routed message is marked `\\Seen` after sink-note writing and daily-note entry updates succeed.
- unrouted messages are left unread.
- routed messages with disallowed senders are left unread.
- reMarkable-routed messages without PDF attachments are left unread.
- duplicate entry lines are not appended.

7. Future extension contract

New email workflows should be added as new handler keys plus new hardcoded routes.
