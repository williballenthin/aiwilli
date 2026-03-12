Weave design

Status: draft
Last updated: 2026-03-12

1. Module layout

- `src/weave/app.py`: main runtime logic, including IMAP handling, calendar scraping, agent-session parsing/rendering, daily-note integration, migration mode, and the integrated `GitHubActivitySyncer`.
- `src/weave/github_activity.py`: GitHub activity fetching and rendering helpers. It still renders the detailed standalone report, and now also renders the compact per-repository daily-note section used by the daemon.
- `tests/test_app.py`: route, handler, daily-note writer, calendar scraper, session rendering, and migration tests.
- `tests/test_github_activity.py`: GitHub activity normalization plus detailed and compact rendering tests.
- `scripts/setup_google_credentials.py`: interactive OAuth setup.
- `scripts/parse_session.py`: standalone CLI for parsing/displaying agent session JSONL files.
- `scripts/render_github_activity.py`: standalone CLI for rendering the detailed grouped GitHub activity report.

2. Core types

- `WeaveConfig` (Pydantic): runtime config loaded from env + CLI args. Route variants are hardcoded, allowed senders come from `WEAVE_ALLOWED_SENDERS`, and GitHub overrides come from args/env.
- `RouteConfig` (Pydantic): route metadata (`to_address`, `allowed_senders`, `handler_key`, sink path).
- `IncomingMessage` (dataclass): normalized unread message from IMAP.
- `Attachment` (dataclass): decoded email attachment.
- `HandlerResult` (dataclass): whether the message was handled, all created paths, and created sink note paths.
- `SessionTurn`, `SessionTokenUsage`, `SessionData` (dataclasses): normalized agent-session model.
- `DailyIndexEntry` (dataclass): one sink note as rendered in a Weave-generated daily note section.
- `DailyNoteWriter`: owns both personal daily-note integration and Weave-generated daily-note regeneration.

3. Shared utilities

- `get_date_folder(output_dir, received)`: creates `YYYY/MM/DD` nested directories under the sink root.
- `sanitize_filename(name)`: strips filesystem-unsafe characters.
- `render_daily_note_relative_path(day, format_string)`: renders Obsidian-style daily note paths for the supported token subset (`YYYY`, `MM`, `DD`). Used both for normal personal-daily-note resolution and explicit layout migration.
- `split_front_matter()`, `parse_front_matter_scalar()`, `get_front_matter_fields()`, `get_note_summary()`, `set_note_summary()`: minimal frontmatter parsing/updating without a YAML dependency.
- `get_managed_section_markers(section_name)`: returns deterministic HTML comment markers for managed Weave sections. GitHub activity keeps its legacy marker names for upgrade compatibility.

4. Runtime flow

1. Parse CLI args.
2. If `--migrate-daily-notes` is set:
   - construct `DailyNoteWriter`
   - optionally migrate the personal daily-note layout (`--daily-note-format`)
   - regenerate Weave daily notes for all discovered days and clean legacy personal daily-note content
   - exit
3. Otherwise build `WeaveConfig` from env + CLI args.
4. Validate Google token exists and initialize `CalendarScraper`.
5. Initialize `DailyNoteWriter` with the generic sink-note summary backfill summarizer.
6. Initialize `AgentSessionScraper` with two summarizers:
   - structured body summary prompt for the note body
   - compact index summary prompt for frontmatter / daily-note grouping
7. Initialize `GitHubActivitySyncer` with the shared `DailyNoteWriter`.
8. Connect to IMAP and process unread routed messages.
9. Each created sink note triggers `DailyNoteWriter.append_note_entry()` / `append_todo_entry()`, which backfills the sink note summary if necessary, rebuilds that day’s Weave daily note, and ensures the personal daily note has the managed embed region.
10. Background maintenance threads handle calendar scraping, agent-session scraping, GitHub activity finalization, and once-per-day Weave daily-note regeneration.

5. Handler implementations

5.1 `VoiceNoteHandler`
- writes `type: transcript` into frontmatter so later Weave-daily-note regeneration can classify the note without relying on the old legacy daily-note entry type.

5.2 `RemarkableSnapshotHandler`
- writes `type: handwriting` into both successful and failure-note frontmatter.

5.3 `TodoHandler`
- writes `type: todo` into frontmatter.
- the daily-note layer no longer inserts an inline checkbox into the personal daily note. Instead, the TODO is rendered in the generated `## TODOs` section.

5.4 `CalendarScraper`
- unchanged at a high level, but its `type` frontmatter (`meeting_notes` / `meeting_chat`) is now consumed by `DailyNoteWriter` when rebuilding Weave daily notes.

5.5 `DailyNoteWriter`

Personal vs generated daily notes:
- personal daily note path comes from `.obsidian/daily-notes.json` `folder` + `format` (default format `YYYY-MM-DD`).
- Weave-generated daily note path is fixed at `weave/daily/YYYY/MM/DD/YYYY-MM-DD.md`.
- personal daily notes get only one managed embed region:
  - `<!-- weave:daily-embed:start -->`
  - `![[weave/daily/...]]`
  - `<!-- weave:daily-embed:end -->`
- the embed region is appended if missing; other personal content is left intact.

Rebuild strategy:
- `append_note_entry()` and `append_todo_entry()` no longer append one line directly into the personal daily note.
- instead they call `_refresh_day(day)`.
- `_refresh_day(day)`:
  - reads any existing personal daily note content
  - preserves an existing GitHub section body from the Weave daily note or legacy personal daily note when no new GitHub body is provided
  - scans `sink/YYYY/MM/DD/*.md`
  - classifies each sink note into `todos`, `meetings`, `capture`, or `agent-sessions`
  - backfills missing sink-note summaries before rendering
  - renders a fully managed Weave daily note with H2 sections and HTML markers
  - writes the Weave daily note only if content changed
  - removes legacy inline `#weave` note lines and legacy managed GitHub sections from the personal daily note
  - ensures the personal daily note contains the managed embed region when the Weave daily note exists

Section rendering:
- section order is fixed: TODOs, Meetings, Capture, Agent sessions, GitHub activity.
- standard note sections render compact bullets with aliased wiki-links and optional summaries.
- agent sessions render as `project -> nested session bullets`; each child uses a shortened session-id tail, compact frontmatter summary, and message count parsed from the metrics table.
- GitHub activity is injected as a pre-rendered compact body and wrapped with the GitHub section markers.

Discovery + sync:
- `sync_all_daily_notes()` discovers days from three sources:
  - sink note day directories
  - personal daily notes (recursive under the configured folder, filtered by ISO date filename stem)
  - existing Weave daily notes
- each discovered day is rebuilt with `_refresh_day(day)`.
- `sync_daily_note(path)` now means “rebuild the day identified by this personal daily note path”.

Layout migration:
- `migrate_personal_daily_layout(format_string)` moves existing personal daily notes to the rendered path for the requested format and writes the new `format` back to `.obsidian/daily-notes.json`.
- if a destination file already exists with different content, it raises `ConfigError` rather than merging.
- empty directories left behind by a move are pruned upward until the configured personal daily-note folder root.

5.6 `GitHubActivitySyncer`
- still fetches recent user events via `gh` and finalizes only stable completed local days.
- still uses a manifest keyed by `<username>:<YYYY-MM-DD>`.
- now calls `render_compact_activity_section()` instead of the detailed per-event renderer.
- writes the compact GitHub body into the Weave daily note through `DailyNoteWriter.upsert_github_activity_section()`.
- `has_github_activity_section(day)` checks both the new Weave daily note and the legacy personal daily note so missing-manifest recovery works across upgrades.

5.7 `AgentSessionScraper`
- constructor now accepts two summarizers:
  - `summarizer`: structured body summary used for the `## Summary` section
  - `index_summarizer`: compact summary written into frontmatter `summary`
- `_sync_session()` renders the conversation once, then runs the two summary prompts independently.
- rendered note filenames remain session-ID based.

5.8 Session rendering
- `render_session_note()` now emits minimal frontmatter: `type`, `summary`, `agent`, `project`, `session_id`, `session_sha256`.
- note metrics moved into the `## Metrics` table. The table includes message count so `DailyNoteWriter` can render compact agent-session bullets without needing extra frontmatter noise.
- `render_session_turns()` now produces Obsidian callouts instead of `**USER:**` / `**ASSISTANT:**` prefixes:
  - `[!note]` for user turns
  - `[!quote]` for assistant turns
- tool names are rendered inside the first assistant callout for the turn.
- because every line is still normal markdown prefixed with `>`, fenced code blocks and inline code render normally inside the callouts.

5.9 `src/weave/github_activity.py`
- `ActivityRecord` now carries optional compact-render metadata: `event_kind`, `detail_text`, `detail_url`.
- normalization sets those fields for commits, PRs, issues, comments/reviews, branches/tags, pushes, and stars.
- the detailed standalone report remains unchanged and still uses `render_activity_report()` / `render_activity_section()`.
- the new `render_compact_activity_section()` groups records by repo and then by normalized event kind, rendering counts plus detail links only when a kind has 3 or fewer records.

6. Threading model

- unchanged structurally: IMAP runs on the main thread, maintenance threads handle calendar, agent sessions, GitHub activity, and daily-note sync.
- `DailyNoteWriter` still uses one `threading.RLock` around summary backfill, day rebuilds, GitHub section updates, and migration logic so concurrent writers cannot interleave file updates.

7. Notes on compatibility

- existing sink notes without the new `type` frontmatter are still classified by heuristics:
  - transcription filename suffix for voice notes
  - PDF attachment frontmatter for handwriting notes
  - subject + `##` heading shape for TODOs
- legacy inline `#weave` personal-daily-note lines remain supported only as migration inputs. `DailyNoteWriter` strips them during daily-note sync and replaces them with the embed-region model.
- legacy managed GitHub sections in personal daily notes are preserved long enough to seed the new Weave daily note during migration, then removed from the personal note.
