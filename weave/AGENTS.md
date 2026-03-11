Weave codebase overview

Status: generated summary
Last updated: 2026-03-03

1. Purpose

Weave is a single-process email ingress daemon for an Obsidian vault.

It monitors one IMAP inbox for unread emails, routes them by recipient variant and sender allowlist, and writes sink notes plus attachments into the vault.

Current hardcoded routes:
- <base-local>+vnote@<domain> from wilbal1087@gmail.com
- <base-local>+rm2@<domain> from my@remarkable.com

For each created sink markdown note, Weave appends an embed line to the corresponding daily note:
- format: - HH:MM ![[<vault-relative-note-path>]]

2. Tech stack

Language/runtime:
- Python 3.12

Primary dependencies:
- imapclient (IMAP access)
- pydantic (config/data validation)
- jinja2 (markdown templating)
- rich (logging/spinner output)

External command dependency:
- llm CLI (PDF transcription), model gemini/gemini-3-flash-preview

Tooling:
- pytest
- ruff
- mypy (strict)
- uv / uv_build

3. Architecture

Current layout is intentionally monolithic:
- src/weave/app.py contains almost all runtime logic.

Runtime flow:
1. Parse CLI args.
2. Load runtime config from env and hardcoded route variants.
3. Connect to IMAP and select INBOX.
4. Fetch unread messages.
5. Normalize envelope fields (sender, recipients, subject, received date).
6. Resolve route by recipient + sender allowlist.
7. Dispatch to route handler.
8. For each created sink note, append an embed line to a daily note.
9. Mark message as seen when handling and daily-note updates succeed.
10. In daemon mode, use IMAP IDLE loop and reconnect on errors.

Core components in src/weave/app.py:
- Exceptions: ConfigError, TranscriptionError
- Helpers: get_variant_address, show_spinner, setup_logging, get_args, main
- Data classes: Attachment, IncomingMessage, HandlerResult
- Protocols: MessageHandler, PdfTranscriber
- Config models: RouteConfig, WeaveConfig
- Services: RouteResolver, MailboxMonitor, LlmPdfTranscriber, VoiceNoteHandler, RemarkableSnapshotHandler, DailyNoteWriter, WeaveService

Handler behavior:
- VoiceNoteHandler: extracts text/plain and attachments, writes transcription markdown plus files.
- RemarkableSnapshotHandler: extracts PDF attachments, transcribes via PdfTranscriber, writes markdown note (or error note on transcription failure).
- DailyNoteWriter: resolves daily note folder from .obsidian/daily-notes.json (folder), falls back to vault root, appends deduplicated embed lines.

4. Repository files and components

Repository files:
- .gitignore
- .python-version
- AGENTS.md
- README.md
- docs/plans/spec.md
- docs/plans/design.md
- pyproject.toml
- src/weave/__init__.py
- src/weave/app.py
- src/weave/cli.py
- tests/test_app.py
- uv.lock

Top-level directories:
- docs/
- src/
- tests/

Source modules:
- src/weave/__init__.py: exports main
- src/weave/cli.py: CLI entry shim
- src/weave/app.py: full application logic

Tests:
- tests/test_app.py: route resolution, address derivation validation, daily-note writer behavior, voice handler output, rm2 handler output and failure handling

5. Runtime inputs and outputs

Required environment variables:
- IMAP_HOST
- IMAP_USER
- IMAP_PASSWORD
- WEAVE_BASE_EMAIL

CLI:
- weave <vault_root> [--poll-interval N] [--once] [--verbose] [--quiet]

Output paths:
- sink notes and attachments under: <vault_root>/sink/<YYYY-MM-DD>/
- attachments under: <vault_root>/sink/<YYYY-MM-DD>/_attachments/
- daily notes under configured daily folder (or vault root fallback)

6. Notes

- Route variants and handler mapping are hardcoded in code; allowed senders come from `WEAVE_ALLOWED_SENDERS` env var.
- Existing design document mentions planned split of app.py into smaller modules; this is not yet implemented.
