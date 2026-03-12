Weave design

Status: draft
Last updated: 2026-03-12

1. Module layout

- `src/weave/app.py`: runtime logic, handlers, scrapers, session parsing/rendering, daily-note generation, and GitHub sync integration
- `src/weave/cli.py`: click-based CLI with subcommands for monitor/sync/import/rebuild
- `src/weave/layout.py`: central vault path layout helper for `daily/YYYY/MM/DD/...`
- `src/weave/github_activity.py`: GitHub fetch/normalize/render helpers
- `tests/test_app.py`: core behavior tests
- `tests/test_cli.py`: CLI smoke tests
- `tests/test_github_activity.py`: GitHub normalization/rendering tests

2. Core types

- `WeaveConfig` (Pydantic): runtime config loaded from env + CLI args for IMAP-backed commands
- `RouteConfig` (Pydantic): route metadata
- `IncomingMessage` (dataclass): normalized unread email
- `Attachment` (dataclass): decoded email attachment
- `HandlerResult` (dataclass): handled flag plus created paths and note paths
- `SessionTurn`, `SessionTokenUsage`, `SessionData` (dataclasses): normalized agent-session model
- `DailyIndexEntry` (dataclass): one imported note as rendered in the generated daily note
- `VaultLayout`: canonical path helper for day roots, category directories, `_attachments`, `_weave`, generated daily notes, and GitHub snapshot files
- `DailyNoteWriter`: owns generated daily-note rendering, personal-note embed synchronization, GitHub snapshot consumption, and legacy cleanup

3. Path model

The canonical Weave path model is now rooted at `daily/YYYY/MM/DD/`.

`VaultLayout` provides the fixed paths used by writers:
- `daily/YYYY/MM/DD/_attachments/`
- `daily/YYYY/MM/DD/_weave/`
- `daily/YYYY/MM/DD/YYYY-MM-DD weave.md`
- `daily/YYYY/MM/DD/agent sessions/`
- `daily/YYYY/MM/DD/meeting notes/`
- `daily/YYYY/MM/DD/transcriptions/`
- `daily/YYYY/MM/DD/scans/`
- `daily/YYYY/MM/DD/todo/`

The personal daily note path is still resolved from `.obsidian/daily-notes.json` via `folder` and `format`.

4. Runtime flow

For `monitor`:
1. Resolve vault root.
2. Build `WeaveConfig` from env + CLI args.
3. Initialize `WeaveService`.
4. Start maintenance threads for calendar, agent sessions, GitHub activity, and daily-note sync.
5. Stay connected to IMAP with IDLE and process routed unread mail.

For one-shot commands:
- `sync` uses `WeaveService.run_single_batch()`.
- `import email` uses `WeaveService.run_email_sync()`.
- `import calendar`, `import agent-sessions`, `import github`, and `rebuild daily` instantiate only the components they need instead of forcing the full IMAP runtime.

5. Handler implementations

5.1 `VoiceNoteHandler`
- writes notes into `transcriptions/`
- writes attachments into `_attachments/`
- emits relative attachment embeds from the note to the day attachment directory

5.2 `RemarkableSnapshotHandler`
- writes notes into `scans/`
- writes PDFs into `_attachments/`
- wraps the OCR/transcription body in `weave:transcription` markers so it can be replaced later without rewriting unrelated note content

5.3 `TodoHandler`
- writes notes into `todo/`
- keeps standalone note files because TODO emails may include attachments and richer context

5.4 `CalendarScraper`
- writes notes/chats into `meeting notes/`
- `scrape_once(days_back=N)` controls the import/backfill window
- the daemon still uses a short recurring window; manual CLI use can backfill farther back

5.5 `AgentSessionScraper`
- writes notes into `agent sessions/`
- still uses a manifest for incremental sync
- keeps two summarizers:
  - structured body summary for the note body
  - compact frontmatter summary for daily-note rendering
- the note body summary is wrapped in `weave:summary` markers

5.6 `GitHubActivitySyncer`
- still fetches recent user events via `gh`
- still finalizes only stable completed local days
- no longer treats the generated daily note as the source of truth
- instead it writes the compact rendered body through `DailyNoteWriter.upsert_github_activity_section()`, which stores a per-day snapshot file under `_weave/github activity.md` and then refreshes the daily note

6. `DailyNoteWriter`

Personal vs generated daily notes:
- personal daily note path comes from `.obsidian/daily-notes.json`
- generated Weave daily note path is fixed at `daily/YYYY/MM/DD/YYYY-MM-DD weave.md`
- personal daily notes get only one managed embed region pointing at the generated Weave daily note

Rebuild strategy:
- `append_note_entry()` and `append_todo_entry()` call `_refresh_day(day)`
- `_refresh_day(day)`:
  - reads the current personal daily note
  - reads GitHub content from `_weave/github activity.md` when present
  - collects imported note entries from the day category directories
  - also reads legacy `sink/YYYY/MM/DD/*.md` files during migration compatibility
  - backfills missing frontmatter summaries when a summarizer is configured
  - renders the generated daily note with deterministic section markers
  - writes the generated daily note only if content changed
  - removes legacy inline `#weave` content from the personal daily note
  - ensures the personal daily note contains the managed embed region when the generated daily note exists

Section rendering:
- order is fixed: TODOs, Meetings, Capture, Agent sessions, GitHub activity
- standard sections render compact bullets with aliased wiki-links and optional summaries
- agent sessions render as project-grouped nested lists using shortened session IDs and parsed message counts
- GitHub activity is copied verbatim from the `_weave/github activity.md` snapshot into the managed daily-note section

Discovery:
- `sync_all_daily_notes()` discovers days from canonical `daily/YYYY/MM/DD/` directories, legacy `sink/YYYY/MM/DD/*.md` paths, and personal daily note paths parsed from filename stems

7. Compatibility notes

- legacy `sink/YYYY/MM/DD/*.md` files are still recognized during daily-note rebuild so the vault can be migrated in stages
- legacy inline `#weave` personal-note lines are still cleanup inputs
- legacy managed GitHub sections are no longer preserved as source material; the new source of truth is `_weave/github activity.md`

8. CLI structure

`src/weave/cli.py` exposes:
- `weave monitor`
- `weave sync`
- `weave import email`
- `weave import calendar --days N`
- `weave import agent-sessions`
- `weave import github`
- `weave rebuild daily`

The CLI uses click because the tool now has multiple operational modes instead of one daemon-only entry point.
