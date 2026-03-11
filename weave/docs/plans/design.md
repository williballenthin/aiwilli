Weave design

Status: draft
Last updated: 2026-03-09

1. Module layout

- `src/weave/app.py`: all runtime logic for now.
- `tests/test_app.py`: route, handler, daily-note writer, and calendar scraper tests.
- `scripts/setup_google_credentials.py`: interactive OAuth setup for Google Calendar/Drive.

2. Core types

- `WeaveConfig` (Pydantic): runtime config loaded from env + CLI args; route variants are hardcoded but allowed senders come from `WEAVE_ALLOWED_SENDERS`. Includes `calendar_source` and `calendar_enabled` fields.
- `RouteConfig` (Pydantic): route metadata (`to_address`, `allowed_senders`, `handler_key`, sink path).
- `get_variant_address(base_email, variant)`: derives `local+variant@domain` from `WEAVE_BASE_EMAIL`.
- `IncomingMessage` (dataclass): normalized unread message from IMAP.
- `Attachment` (dataclass): decoded email attachment.
- `HandlerResult` (dataclass): whether the message was handled, all created paths, and created sink note paths.
- `DailyNoteWriter`: resolves daily-note folder and appends timestamped embed lines. Thread-safe via `threading.Lock`.

3. Shared utilities

- `get_date_folder(output_dir, received)`: module-level function that creates `YYYY/MM/DD` nested directory with `_attachments` subfolder. Used by all handlers and the calendar scraper.
- `sanitize_filename(name)`: strips filesystem-unsafe characters from names.

4. Runtime flow

1. Parse CLI args (including `--source`, `--no-calendar`).
2. Build `WeaveConfig` from env: route variants (`+vnote`, `+rm2`, `+todo`) resolved from `WEAVE_BASE_EMAIL`, allowed senders from `WEAVE_ALLOWED_SENDERS`.
3. If calendar is enabled, validate Google token exists and initialize `CalendarScraper`.
4. Connect with `IMAPClient` and select `INBOX`.
5. Fetch unread messages with envelope + RFC822 payload.
6. Normalize sender/to-addresses and resolve route.
7. Dispatch to handler by `handler_key`.
8. For each created sink note path, append a timestamped embed line to that day's daily note.
9. If handler result says handled and daily-note updates succeeded, mark message as seen.
10. In daemon mode, enter IMAP IDLE and repeat on notifications; calendar scraper runs in a background thread.

5. Handler implementations

5.1 `VoiceNoteHandler`
- extracts text/plain body from multipart email
- extracts all attachment parts marked `attachment`
- writes date folder + `_attachments` via shared `get_date_folder`
- writes one markdown note with YAML frontmatter and Obsidian attachment embeds

5.2 `RemarkableSnapshotHandler`
- extracts `application/pdf` attachments
- writes each PDF file under `_attachments`
- asks `PdfTranscriber` for markdown transcription
- writes markdown note with embed and transcription
- writes failure note when transcription throws `TranscriptionError`

5.3 `TodoHandler`
- extracts text/plain body from multipart email
- extracts all attachment parts marked `attachment`
- sanitizes subject for use as filename (`sanitize_filename`)
- writes date folder + `_attachments` via shared `get_date_folder`
- writes one markdown note with YAML frontmatter, `## <subject>` heading, body text, and Obsidian attachment embeds
- returns `todo_entries` on `HandlerResult` instead of `note_paths`, which triggers a `- [ ] TODO:` checkbox line on the daily note

5.4 `CalendarScraper`
- initialized with `output_dir`, `source` tag, and a `DriveExporter` instance
- `scrape_once()` fetches events from past 7 days via Google Calendar API, iterates events with doc/chat attachments
- exports Google Docs as markdown via `DriveExporter.export_document()`
- downloads chat transcripts via `DriveExporter.get_media()`
- for shared notes (title starts with "Notes - "), extracts only the section matching the event date using `extract_section_for_date()`
- uses file-existence check as cache to avoid re-exporting
- returns `list[tuple[datetime, Path]]` for daily note embedding
- helper predicates: `is_gemini_notes()`, `is_shared_notes()`

5.5 `DailyNoteWriter`
- reads daily-note folder from `<vault_root>/.obsidian/daily-notes.json` key `folder`
- falls back to vault root if config is missing/invalid
- resolves daily note filename as `YYYY-MM-DD.md` from message received date
- appends `- HH:MM ![[<vault-relative-note-path>]]` at end of daily note
- deduplicates exact embed lines
- `append_todo_embed` renders `- [ ] TODO: <subject> [[path]]` for todo handler entries
- shared `append_line` method handles file I/O and dedup for both embed styles
- `threading.Lock` protects `append_line` for concurrent access from IMAP and calendar threads

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
- In daemon mode, the calendar scraper runs in a daemon thread calling `run_calendar_loop()` with a 5-minute sleep via `_shutdown.wait(timeout=300)`.
- The IMAP loop runs on the main thread.
- `DailyNoteWriter.append_line` is protected by a `threading.Lock` since both threads write daily notes.
- Signal handlers (SIGINT, SIGTERM) set `_shutdown` before exiting.
- In `--once` mode, calendar scrape runs synchronously after IMAP batch.

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
- add route-level metrics and structured JSON run report
