Weave agent notes

Purpose
- Weave ingests outside activity into an Obsidian vault.
- The main implemented workflows are:
  - IMAP email routing into sink notes
  - Google Calendar meeting note/chat export
  - AI agent session import from Claude Code and Pi JSONL logs
  - GitHub activity import into daily notes
- `src/weave/github_activity.py` provides the GitHub fetch/render helpers used by both the standalone script and the main daemon flow.

Read these first
1. `docs/plans/spec.md` for intended user-facing behavior and output layout.
2. `docs/plans/design.md` for the current architecture and major components.
3. `src/weave/app.py` for the real implementation. Almost everything lives here.
4. `tests/test_app.py` for the most useful executable map of expected behavior and edge cases.
5. `src/weave/github_activity.py` and `tests/test_github_activity.py` if working on the GitHub activity prototype.

Project shape
- The codebase is still monolithic.
- `src/weave/app.py` contains:
  - CLI entry logic
  - runtime config loading
  - IMAP polling and IDLE loop
  - route resolution
  - email handlers
  - calendar scraping
  - agent session parsing and import
  - daily note writing and sync
- `src/weave/cli.py` and `src/weave/__init__.py` are thin entry shims.

High-level runtime flow
- `main()` parses args, resolves the vault root from CLI or env, and builds `WeaveConfig` from env plus CLI inputs.
- `WeaveService` wires the system together.
- `MailboxMonitor` fetches unread IMAP messages and normalizes them into `IncomingMessage`.
- `RouteResolver` matches each message by recipient address and allowed sender.
- A handler writes sink notes and attachments.
- `DailyNoteWriter` regenerates the Weave-managed daily note and keeps the personal daily-note embed region in sync.
- Background maintenance also runs calendar scraping, agent session scraping, GitHub activity sync, and daily-note sync.

Important classes and functions
- `WeaveConfig`, `RouteConfig`: runtime configuration and hardcoded route definitions.
- `MailboxMonitor`: IMAP connection lifecycle, unread fetch, envelope decoding, mark-seen.
- `RouteResolver`: recipient-plus-sender matching.
- `VoiceNoteHandler`: saves plain-text body plus attachments.
- `RemarkableSnapshotHandler`: saves PDFs and transcribes them through `llm`.
- `TodoHandler`: turns email into a TODO note and daily-note checkbox entry.
- `CalendarScraper`: exports Google Docs and chat attachments from recent calendar events.
- `AgentSessionScraper`: imports Claude/Pi session logs, uses a manifest for incremental sync, and renders session notes.
- `DailyNoteWriter`: central place for daily-note path resolution, dedupe, summary backfill, and sync.
- `WeaveService`: top-level orchestration. Start here if you need the overall control flow.
- `parse_session()`, `parse_claude_session()`, `parse_pi_session()`, `render_session_note()`: the agent-session import path.
- `get_date_folder()`, `sanitize_filename()`, `get_variant_address()`: shared path and naming helpers.

Filesystem model
- Generated notes go under `<vault>/sink/YYYY/MM/DD/`.
- Attachments go under `<vault>/sink/YYYY/MM/DD/_attachments/`.
- Daily note folder comes from `<vault>/.obsidian/daily-notes.json` key `folder`, with vault root as fallback.
- Daily-note entries managed by Weave always end with `#weave`; `DailyNoteWriter` owns dedupe and rewrite behavior.

Where to look for common tasks
- Routing bug: `WeaveConfig.from_runtime()`, `RouteResolver`, `WeaveService.get_processed_count()`.
- Note filename/content bug: the relevant handler and the Jinja templates near the top of `src/weave/app.py`.
- Daily note duplication or summary issues: `DailyNoteWriter` and the frontmatter helpers around `split_front_matter()`.
- Calendar behavior: `CalendarScraper` plus `scripts/setup_google_credentials.py`.
- Agent session import issue: `AgentSessionScraper`, session parsing helpers, and `docs/research/agent-sessions.md`.
- GitHub activity work: `src/weave/github_activity.py`.

How to extend it
- New email workflow:
  - add a route in `WeaveConfig.from_runtime()`
  - add the handler in `WeaveService.get_handlers()`
  - return the right `HandlerResult` so daily-note updates happen correctly
  - add tests in `tests/test_app.py`
- Keep summary generation/backfill logic inside `DailyNoteWriter`, not inside individual handlers.
- If you split `app.py`, preserve the existing boundaries: monitor, routing, handlers, scrapers, daily-note writer, service.

Practical notes
- `README.md` is narrower than the current code. The codebase now also includes calendar scraping, TODO handling, agent session import, and GitHub activity import.
- Local machine configuration for this repo should be read from `${XDG_CONFIG_HOME:-~/.config}/wballenthin/weave/secrets.env`.
- In this checkout, `../secrets.env` may exist as a compatibility symlink; prefer the XDG file as the canonical source of truth.
- For local Obsidian runs, look for `WEAVE_VAULT_ROOT` in that secrets file. `OBSIDIAN_VAULT_ROOT` is only a compatibility fallback.
- If docs and code disagree, verify behavior in `src/weave/app.py` and tests first, then update `docs/plans/spec.md` and `docs/plans/design.md`.
- The current code initializes calendar support eagerly in `WeaveService`; confirm startup assumptions in code before relying on doc text about optional calendar behavior.
