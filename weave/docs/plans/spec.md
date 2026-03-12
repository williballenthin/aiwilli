Weave specification

Status: draft
Last updated: 2026-03-12

1. Purpose

Weave monitors one IMAP inbox and routes unread emails to handler logic based on the recipient address. It also scrapes Google Calendar meeting notes and chat transcripts on a recurring schedule, imports AI agent session transcripts (Claude Code, Pi Agent), and imports finalized GitHub activity.

2. Invocation

Command:
- `weave [<vault_root>] [--poll-interval N] [--once] [--verbose] [--quiet] [--source TAG] [--agent-sessions DIR] [--github-user USER] [--github-timezone TZ]`

Behavior:
- `--once` processes one unread batch plus one calendar scrape plus one agent session scan plus one GitHub activity sync pass, runs one daily-note sync pass, then exits.
- default mode stays connected and loops with IMAP IDLE; background maintenance starts immediately at startup.
- calendar scraping, agent session scraping, GitHub activity sync, and daily-note sync each run in their own daemon thread.
- calendar scraping and agent session scraping repeat every 5 minutes while the process is running.
- GitHub activity sync checks hourly.
- daily-note sync checks every 5 minutes but performs work at most once per local calendar day.
- vault root resolution order is: positional `<vault_root>`, then `WEAVE_VAULT_ROOT`, then `OBSIDIAN_VAULT_ROOT`.
- when no vault root can be resolved, startup fails with a configuration error.
- the resolved vault root must exist.
- for deployed/systemd runs, the recommended configuration is to set `WEAVE_VAULT_ROOT` in the environment file and omit the positional `<vault_root>` argument from `ExecStart`.
- `--source TAG` sets the calendar source tag in front matter (default: `@hex-rays.com`).
- calendar scraping is always enabled in normal daemon/once mode.
- `--agent-sessions DIR` points to the directory containing agent session JSONL files. Can also be set via `WEAVE_AGENT_SESSIONS_DIR` env var. If not set, agent session scraping is disabled.
- `--github-user USER` overrides the GitHub username to query. If omitted, Weave uses the authenticated `gh` user.
- `--github-timezone TZ` sets the local timezone used for GitHub day boundaries and the stabilization cutoff. Can also be set via `WEAVE_GITHUB_TIMEZONE`.

3. Required runtime environment

Normal daemon/once mode requires:
- `IMAP_HOST`
- `IMAP_USER`
- `IMAP_PASSWORD`
- `WEAVE_BASE_EMAIL` (base mailbox, e.g. `name@example.com`)
- `WEAVE_ALLOWED_SENDERS` (comma-separated list of email addresses allowed to send to any route)
- a vault root provided either by positional `<vault_root>` or by `WEAVE_VAULT_ROOT` (preferred for deployed runs); `OBSIDIAN_VAULT_ROOT` is accepted as a compatibility fallback.

Calendar scraping also requires:
- Google OAuth token at `$XDG_CONFIG_HOME/wballenthin/weave/token.json` (created via `scripts/setup_google_credentials.py`)
- Google OAuth client credentials at `$XDG_CONFIG_HOME/wballenthin/weave/credentials.json`

Agent session scraping also requires:
- `WEAVE_AGENT_SESSIONS_DIR` or `--agent-sessions` pointing to a directory with `claude/` and/or `pi/` subdirectories containing JSONL session files.

GitHub activity import also requires:
- `gh` CLI installed and authenticated for the desired account, unless `--github-user` / `WEAVE_GITHUB_USER` targets a public account and the local `gh` auth still has enough access for the request.
- optional `WEAVE_GITHUB_USER` to override the account whose activity is imported.
- optional `WEAVE_GITHUB_TIMEZONE` to set local day boundaries and the stabilization cutoff.


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

Date directory format: sink handlers and calendar/session imports use nested `YYYY/MM/DD` directories under the output root.

5.1 Voice handler output
- note path: `<output>/<YYYY>/<MM>/<DD>/<HHMM> - transcription.md`
- attachment path: `<output>/<YYYY>/<MM>/<DD>/_attachments/<HHMM> - <filename>`
- note contains YAML frontmatter including `type: transcript` and `summary`, plus the email plain-text body.

5.2 reMarkable handler output
- saved pdf: `<output>/<YYYY>/<MM>/<DD>/_attachments/<HHMM> - <stem>.pdf`
- note path: `<output>/<YYYY>/<MM>/<DD>/<HHMM> - <stem>.md`
- note contains YAML frontmatter including `type: handwriting`, `summary`, and an embed link to the saved PDF.
- transcription is generated through the `llm` CLI against model `gemini/gemini-3-flash-preview`.
- on transcription failure, Weave still writes an error note and marks the message as seen.

5.3 TODO handler output
- note path: `<output>/<YYYY>/<MM>/<DD>/<HHMM> - <sanitized-subject>.md`
- attachment path: `<output>/<YYYY>/<MM>/<DD>/_attachments/<HHMM> - <filename>`
- subject is sanitized for filesystem safety (colons, quotes, slashes etc. replaced with dashes, trailing dashes stripped, max 100 chars).
- note contains YAML frontmatter including `type: todo`, `summary`, a `## <subject>` heading, the email plain-text body, and Obsidian embed links for any attachments.

5.4 Calendar scraper output
- scrapes Google Calendar events from the past 7 days.
- for each event with Google Doc attachments, exports the doc as markdown.
- for each event with chat transcript attachments (text/plain ending in `- Chat`), downloads the raw content.
- note path: `<output>/<YYYY>/<MM>/<DD>/<HHMM> - <sanitized-event-name>.md`
- if multiple doc attachments and one is Gemini notes: `<HHMM> - <event-name> (Gemini).md`
- chat transcripts: `<HHMM> - <event-name> (chat).md`
- front matter includes: `summary`, `source`, `type` (`meeting_notes` or `meeting_chat`), calendar, event name, date, attended status, doc URL, event URL, attendees list.
- shared notes (title starts with `Notes - `) are section-extracted for the event date only.
- file-existence check serves as cache; existing files are not re-exported.
- events without doc or chat attachments are skipped.
- attendance is determined from the self-attendee's `responseStatus`; organizer-only events default to attended.

5.5 Daily note integration
- Weave no longer writes generated activity lines directly into the user’s primary personal daily note body.
- Personal daily note folder is loaded from `<vault_root>/.obsidian/daily-notes.json` key `folder`.
- Personal daily note format is loaded from `.obsidian/daily-notes.json` key `format`; default is `YYYY-MM-DD` when the key is missing.
- Weave-generated daily note path is fixed at `<vault_root>/weave/daily/<YYYY>/<MM>/<DD>/<YYYY-MM-DD>.md`.
- The personal daily note contains only a managed embed region:
  - `<!-- weave:daily-embed:start -->`
  - `![[weave/daily/<YYYY>/<MM>/<DD>/<YYYY-MM-DD>.md]]`
  - `<!-- weave:daily-embed:end -->`
- In normal operation, that embed region is the only content Weave adds to a personal daily note.
- Weave-generated daily notes are fully regenerable. They may be deleted and rebuilt from sink notes plus preserved GitHub sections.
- Weave-generated daily notes render H2 sections in this order when the section has content:
  - `## TODOs`
  - `## Meetings`
  - `## Capture`
  - `## Agent sessions`
  - `## GitHub activity`
- Each generated section is wrapped in deterministic HTML comment markers so it can be rewritten precisely.
- TODO items render as checkbox bullets with compact aliased wiki-links and optional summaries.
- meeting notes/chats and capture items render as compact bullets with aliased wiki-links and optional summaries.
- agent sessions render as a nested list grouped by project; child bullets use a shortened session ID as link text, plus a compact summary and message count.
- current agent-session imports generate that frontmatter summary with a dedicated prompt that targets a single plain-text phrase of about 12 words and caps it at 12 words.
- when an existing older agent-session note still carries a longer legacy summary, the Weave daily-note renderer truncates it to roughly 12 words for scanability without modifying the note itself.
- GitHub activity renders as a compact repository index; see section 5.7.
- Weave still stores/reuses a per-note frontmatter `summary` on generated sink notes. If a sink note has no summary and a summarizer is configured, Weave backfills it into the sink note itself and then reuses it in the Weave-generated daily note.
- Once per local day, daily-note sync regenerates Weave daily notes from current sink-note metadata and removes legacy inline `#weave` entries / legacy managed GitHub sections from personal daily notes while preserving all non-Weave personal content.

5.6 Agent session scraper output
- scans `claude/` and `pi/` subdirectories of the configured agent sessions directory for canonical session `.jsonl` files.
- subagent session files (under `*/subagents/`) are skipped.
- non-canonical `.jsonl` artifacts such as harness cache/export files are ignored. Claude imports require a UUID filename; Pi imports require the timestamp-plus-session-id filename form.
- parses both Claude Code and Pi Agent JSONL formats, auto-detecting by first line.
- session identity comes from the harness session ID: Claude usually uses the filename stem; Pi usually uses the session UUID from the timestamp-prefixed filename. Parsed JSONL data can also supply the session ID.
- for each session with at least one user turn, produces a markdown note with:
  - YAML front matter: `type`, compact `summary`, `agent`, `project`, `session_id`, `session_sha256`.
  - an LLM-generated structured summary section (goal, decisions, work completed, topics).
  - a metrics table in the note body.
  - the full conversation rendered as Obsidian callouts (`note` for user, `quote` for assistant) so markdown/code inside the body still renders normally.
- note path: `<output>/<YYYY>/<MM>/<DD>/<session-id>.md`
- date directory is based on session start time.
- frontmatter `summary` is a separate compact index summary intended for the Weave-generated daily note. It is generated with a dedicated agent-session index prompt that aims for a single plain-text phrase of about 12 words while capping the result at 12 words, with a rewrite pass if the first LLM output is verbose or misformatted.
- the structured summary section in the note body is generated independently.
- sync state is tracked in a JSON manifest at `$XDG_CACHE_HOME/wballethin/weave/agent-session-manifest.json` (falling back to `~/.cache/...`). Missing or malformed manifests are treated as cache misses and are regenerated on the next scan.
- on each scan, agent session files modified within the last 7 days are treated as mutable and are checked against the manifest. Older files are treated as immutable once they have a manifest entry and an existing sink note.
- the manifest stores per-source-file session ID, SHA-256, sink path, and source mtime for incremental sync.
- if a mutable file’s SHA-256 changes, Weave rewrites the sink note and updates that day’s Weave-generated daily note.
- changed agent-session notes are linked into Weave-generated daily notes incrementally as each note is written, rather than only after the entire scan finishes.
- zero-byte session files are treated as empty inputs and skipped without warning spam.
- each agent-session scan emits a JSON sync report to stdout summarizing scanned, imported, updated, unchanged, immutable-skipped, empty-skipped, and failed sessions.

5.7 GitHub activity import
- GitHub activity import does not create sink notes.
- Weave reads the recent GitHub user events feed via `gh` and expands pushes through compare requests so commit activity can be counted and linked directly.
- imported GitHub activity is written into the `## GitHub activity` section of the Weave-generated daily note, not directly into the personal daily note.
- the managed GitHub section is wrapped with deterministic HTML comment markers so it can be preserved across Weave daily-note rebuilds.
- repository output is a compact bullet list. There are no per-repository subheadings inside the Weave-generated daily note.
- each repository bullet links to the repository and summarizes counts by activity kind (for example commits, PRs, comments, issues, branches, tags, pushes, stars).
- when a kind has 3 or fewer events, the count includes compact linked details in parentheses:
  - commits use 4-character commit prefixes.
  - PRs/issues/comments use linked `#<number>` references when available.
- when a kind has more than 3 events, only the count is shown.
- Weave never imports the current local day.
- Weave only imports a completed day once that day has passed a 6-hour stabilization window in the configured local timezone. Concretely, a day becomes eligible at `06:00` on the following local day.
- once a local day is imported, Weave records that fact in `$XDG_CACHE_HOME/wballethin/weave/github-activity-manifest.json` and does not re-render the day on later syncs.
- if the manifest is missing but the Weave daily note already contains the managed GitHub section for that day, Weave treats the day as already imported and rebuilds the manifest entry instead of rewriting the note.
- for backward compatibility during upgrades, if the manifest is missing but a legacy managed GitHub section is still present in the personal daily note, Weave also treats that day as already imported until daily-note sync rewrites it.
- when Weave rebuilds daily notes from an existing legacy detailed GitHub section, it compacts that legacy section into the new repository-summary format instead of preserving the old verbose event list.
- days with no GitHub activity are left unchanged; Weave only adds the section when there is activity to render.
- the import is best-effort and limited by the GitHub user events feed window; if Weave is not running for too long and relevant events fall out of the recent feed, historical backfill is not guaranteed.

6. Message visibility behavior

- a successfully handled routed message is marked `\Seen` after sink-note writing and Weave daily-note regeneration succeed.
- unrouted messages are left unread.
- routed messages with disallowed senders are left unread.
- reMarkable-routed messages without PDF attachments are left unread.

7. Future extension contract

New email workflows should be added as new handler keys plus new hardcoded routes.
