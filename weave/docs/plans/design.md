Weave design

Status: draft
Last updated: 2026-03-11

1. Module layout

- `src/weave/app.py`: all runtime logic for now.
- `src/weave/github_activity.py`: standalone GitHub activity timeline prototype; fetches recent user events via `gh`, expands pull requests and pushes, normalizes them, and renders a grouped markdown report organized by day and repository.
- `tests/test_app.py`: route, handler, daily-note writer, calendar scraper, and agent session tests.
- `tests/test_github_activity.py`: GitHub activity normalization and rendering tests.
- `scripts/setup_google_credentials.py`: interactive OAuth setup for Google Calendar/Drive.
- `scripts/parse_session.py`: standalone CLI for parsing/displaying agent session JSONL files.
- `scripts/render_github_activity.py`: standalone CLI for rendering grouped GitHub activity from the recent user events feed.
- `docs/research/agent-sessions.md`: research notes on Claude Code and Pi Agent JSONL formats.
- `docs/research/github-activity.md`: GitHub activity API research and design constraints.

2. Core types

- `WeaveConfig` (Pydantic): runtime config loaded from env + CLI args; route variants are hardcoded but allowed senders come from `WEAVE_ALLOWED_SENDERS`. Includes `calendar_source` and `agent_sessions_dir` fields.
- `RouteConfig` (Pydantic): route metadata (`to_address`, `allowed_senders`, `handler_key`, sink path).
- `get_variant_address(base_email, variant)`: derives `local+variant@domain` from `WEAVE_BASE_EMAIL`.
- `IncomingMessage` (dataclass): normalized unread message from IMAP.
- `Attachment` (dataclass): decoded email attachment.
- `HandlerResult` (dataclass): whether the message was handled, all created paths, and created sink note paths.
- `DailyNoteWriter`: resolves daily-note folder, appends timestamped embed lines, and backfills note `summary` frontmatter. Thread-safe via `threading.RLock`.

3. Shared utilities

- `get_date_folder(output_dir, received)`: module-level function that creates `YYYY/MM/DD` nested directory with `_attachments` subfolder. Used by all handlers and the calendar scraper.
- `sanitize_filename(name)`: strips filesystem-unsafe characters from names.

3.1 GitHub activity prototype rendering

- `scripts/render_github_activity.py` is intentionally standalone and does not write vault notes.
- output grouping is `date -> repository -> chronological events`; there are no per-type subheadings inside a repository section.
- most events render as a single markdown bullet line whose timestamp is also the primary link target, e.g. `[10:28:20](...) pushed 4 commits to main`.
- push events may include nested commit bullets under the top-level push line, each rendered as `[sha](commit-url) headline`.
- issue comments, review submissions, and review comments render the comment/review body snippet inline on the main bullet line.
- star events render both the timestamp link and the repository name link to the repository HTML URL.

4. Runtime flow

1. Parse CLI args (including `--source`).
2. Build `WeaveConfig` from env: route variants (`+vnote`, `+rm2`, `+todo`) resolved from `WEAVE_BASE_EMAIL`, allowed senders from `WEAVE_ALLOWED_SENDERS`.
3. Validate Google token exists and initialize `CalendarScraper`.
4. Connect with `IMAPClient` and select `INBOX`.
5. Fetch unread messages with envelope + RFC822 payload.
6. Normalize sender/to-addresses and resolve route.
7. Dispatch to handler by `handler_key`.
8. For each created sink note path, append a timestamped embed line to that day's daily note.
9. If handler result says handled and daily-note updates succeeded, mark message as seen.
10. In daemon mode, enter IMAP IDLE and repeat on notifications; a background maintenance thread handles calendar scraping, agent session scraping, and once-per-day daily-note sync.

5. Handler implementations

5.1 `VoiceNoteHandler`
- extracts text/plain body from multipart email
- extracts all attachment parts marked `attachment`
- writes date folder + `_attachments` via shared `get_date_folder`
- writes one markdown note with YAML frontmatter, including `summary: ""`, and Obsidian attachment embeds

5.2 `RemarkableSnapshotHandler`
- extracts `application/pdf` attachments
- writes each PDF file under `_attachments`
- asks `PdfTranscriber` for markdown transcription
- writes markdown note with frontmatter, including `summary: ""`, plus embed and transcription
- writes failure note when transcription throws `TranscriptionError`

5.3 `TodoHandler`
- extracts text/plain body from multipart email
- extracts all attachment parts marked `attachment`
- sanitizes subject for use as filename (`sanitize_filename`)
- writes date folder + `_attachments` via shared `get_date_folder`
- writes one markdown note with YAML frontmatter, including `summary: ""`, a `## <subject>` heading, body text, and Obsidian attachment embeds
- returns `todo_entries` on `HandlerResult` instead of `note_paths`, which triggers a `- [ ] TODO:` checkbox line on the daily note

5.4 `CalendarScraper`
- initialized with `output_dir`, `source` tag, and a `DriveExporter` instance
- `scrape_once()` fetches events from past 7 days via Google Calendar API, iterates events with doc/chat attachments
- exports Google Docs as markdown via `DriveExporter.export_document()`
- downloads chat transcripts via `DriveExporter.get_media()`
- for shared notes (title starts with "Notes - "), extracts only the section matching the event date using `extract_section_for_date()`
- writes calendar/chat frontmatter with an empty `summary` field so later summary backfills have a stable location
- uses file-existence check as cache to avoid re-exporting
- returns `list[tuple[datetime, Path, str]]` for daily note embedding (datetime, path, entry_type)
- helper predicates: `is_gemini_notes()`, `is_shared_notes()`

5.5 `DailyNoteWriter`
- reads daily-note folder from `<vault_root>/.obsidian/daily-notes.json` key `folder`
- falls back to vault root if config is missing/invalid
- resolves daily note filename as `YYYY-MM-DD.md` from message received date
- accepts an optional `NoteSummarizer` for generating one-sentence summaries
- `append_note_entry(received, note_path, entry_type)` reads or backfills the note's frontmatter `summary`, then upserts a managed line rendered as `- <type>: [[path]] - <summary> #weave`
- `append_todo_entry(received, note_path)` follows the same summary/backfill path and upserts `- [ ] todo: [[path]] - <summary> #weave`
- helper functions `split_front_matter()`, `get_note_summary()`, and `set_note_summary()` implement minimal summary-field parsing/updating without adding a YAML dependency
- if a note already has a non-empty `summary` field, Weave reuses it and skips the LLM call
- if a note lacks frontmatter entirely, `set_note_summary()` prepends a minimal frontmatter block containing only `summary`
- `sync_all_daily_notes()` scans `YYYY-MM-DD.md` files in the configured daily-note folder and calls `sync_daily_note()` on each
- `sync_daily_note()` rewrites only managed lines that exactly match the note/todo `#weave` formats; unmanaged lines are preserved verbatim
- sync resolves the linked path back to a vault file, reads its current frontmatter `summary`, and re-renders the managed line without invoking the summarizer
- if the linked note is missing or unreadable during sync, the original daily-note line is left untouched
- all lines end with `#weave` tag for future regeneration of managed lines
- deduplication and refresh are both link-based: `_upsert_line()` finds an existing managed line for the same `[[link]]` + `#weave` tag and either leaves it unchanged or replaces it in place with the refreshed summary text
- `threading.RLock` protects the full append path, including summary backfill and daily-note write, for concurrent access from IMAP and calendar threads

5.6 `AgentSessionScraper`
- initialized with `sessions_dir`, `output_dir`, and optional `NoteSummarizer`
- `scrape_once()` finds all `.jsonl` files under `claude/` and `pi/` subdirectories (skipping `subagents/`)
- keeps a JSON manifest at `$XDG_CACHE_HOME/wballethin/weave/agent-session-manifest.json`; if the file is missing or malformed it is ignored and rebuilt from the source tree
- manifest entries are keyed by source file path and store `session_id`, `session_sha256`, `sink_path`, and `source_mtime_ns`
- each scan stats every source file, treats files with an mtime in the last 7 days as mutable, and otherwise trusts the manifest + existing sink note without rereading file contents
- mutable files skip reparsing when `st_mtime_ns` matches the manifest; otherwise Weave hashes the file and only reparses when the SHA-256 changed or the sink note disappeared
- session note filenames are the session ID (`<YYYY>/<MM>/<DD>/<session-id>.md`) rather than a project/time slug
- rendered session notes include frontmatter `summary: ""`, `session_id`, and `session_sha256`, plus the structured LLM summary section, metrics table, and conversation turns
- `WeaveService` wires the agent-session note-body summarizer to `AGENT_SESSION_SUMMARY_PROMPT`, distinct from the generic daily-index/frontmatter summary prompt
- `scrape_once()` returns both changed-note results for daily-note updates and an `AgentSessionSyncReport`; `WeaveService.run_agent_session_scrape()` prints that report as JSON to stdout

5.7 Session parsing
- `SessionTurn`, `SessionTokenUsage`, `SessionData` dataclasses hold parsed session data
- `detect_session_format()` reads the first JSONL line to distinguish Claude vs Pi format
- `parse_claude_session()` handles streaming dedup (multiple records per `message.id`, take last for accurate `output_tokens`)
- `parse_pi_session()` extracts cost data and tree-structured turns
- `_is_human_user_msg()` filters out tool results and meta/system messages from Claude sessions
- `render_session_turns()` produces markdown conversation output
- `render_session_note()` produces the full markdown file with Jinja2 template

5.8 `NoteSummarizer` / `LlmNoteSummarizer`
- protocol: `NoteSummarizer.summarize(content) -> str`
- concrete: `LlmNoteSummarizer(prompt=..., model=...)` shells out to `llm` CLI with a caller-supplied prompt
- current prompt wiring uses `SUMMARY_PROMPT` for frontmatter/daily-note summaries and `AGENT_SESSION_SUMMARY_PROMPT` for the agent-session note body summary
- on failure (process error, command not found), logs warning and returns empty string
- tests use `StaticSummarizer` that returns predetermined text without mocks

6. Transcription abstraction

- protocol: `PdfTranscriber.get_transcription(pdf_path) -> str`
- concrete: `LlmPdfTranscriber` that shells out to `llm`
- tests use deterministic in-memory transcriber classes without mocks

7. Drive export abstraction

- protocol: `DriveExporter` with `export_document(file_id) -> bytes` and `get_media(file_id) -> bytes`
- concrete: `GoogleDriveExporter` wraps `googleapiclient.discovery.build("drive", "v3")`
- tests use `StaticDriveExporter` that returns predetermined bytes without mocks

8. Threading model

- `WeaveService` owns a `threading.Event` (`_shutdown`) for coordinated shutdown.
- In daemon mode, a maintenance thread runs `run_background_loop()` every 5 minutes via `_shutdown.wait(timeout=300)`.
- Each maintenance iteration runs calendar scrape, agent session scrape, and a once-per-day `run_daily_note_sync()` pass.
- `run_daily_note_sync()` uses `WeaveService._last_daily_note_sync_on` to ensure at most one sync pass per local calendar day.
- The IMAP loop runs on the main thread.
- `DailyNoteWriter` uses a `threading.RLock` across summary backfill and daily-note writes since both threads can touch the same notes.
- Signal handlers (SIGINT, SIGTERM) set `_shutdown` before exiting.
- In `--once` mode, calendar scrape, agent session scrape, and one daily-note sync pass run synchronously after the IMAP batch.

9. Credential setup

- `scripts/setup_google_credentials.py` imports `CalendarScraper.get_google_credentials()` and runs the interactive OAuth flow.
- Credentials stored at `$XDG_CONFIG_HOME/wballenthin/weave/credentials.json` (client secrets) and `token.json` (OAuth token).
- At startup, `WeaveService` validates the token exists; if missing, raises `ConfigError` directing the user to run the setup script.

10. Consolidation notes from previous scripts

The old standalone scripts had duplicated blocks for:
- IMAP connection lifecycle
- unread message scanning
- envelope decoding
- date-folder note writing
- long-running loop and reconnect

Weave keeps one monitor/loop and routes to specialized handlers. The previous per-script behavior is preserved for naming and markdown output shape.

The `scripts/poc.py` calendar scraper was consolidated into the `CalendarScraper` class following the same protocol-based testing pattern as `PdfTranscriber`/`LlmPdfTranscriber`.

11. Planned next refactors

- split `app.py` into `mailbox.py`, `routes.py`, `handlers/`, and `cli.py`
- add handler for links/quick notes
- add route-level metrics and broader structured JSON run reports beyond agent-session sync
