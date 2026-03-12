Weave specification

Status: draft
Last updated: 2026-03-12

1. Purpose

Weave imports outside activity into an Obsidian vault. The implemented sources are routed IMAP email, Google Calendar meeting notes/chats, Claude Code and Pi agent session logs, and GitHub activity.

2. Invocation

Commands:
- `weave monitor [<vault_root>] [options]`
- `weave sync [<vault_root>] [options]`
- `weave import email [<vault_root>] [options]`
- `weave import calendar [<vault_root>] [options] [--days N]`
- `weave import agent-sessions [<vault_root>] [options]`
- `weave import github [<vault_root>] [options]`
- `weave rebuild daily [<vault_root>] [--verbose] [--quiet]`

Shared option behavior:
- vault root resolution order is positional `<vault_root>`, then `WEAVE_VAULT_ROOT`, then `OBSIDIAN_VAULT_ROOT`
- the resolved vault root must exist
- `--verbose` enables debug logging
- `--quiet` reduces logging to errors only

Command behavior:
- `monitor` runs the long-lived IMAP/maintenance daemon
- `sync` runs one email batch, one calendar import pass, one agent-session import pass, one GitHub import pass, one daily-note rebuild pass, then exits
- `import email` processes one email batch only
- `import calendar` imports calendar notes/chats and supports backfill via `--days` (default: 7)
- `import agent-sessions` imports session JSONL files from `--agent-sessions` or `WEAVE_AGENT_SESSIONS_DIR`
- `import github` imports finalized GitHub activity and stores a per-day snapshot file
- `rebuild daily` regenerates Weave daily notes and personal-note embed regions from imported notes plus GitHub snapshot files

3. Required runtime environment

Email-monitoring commands (`monitor`, `sync`, `import email`) require:
- `IMAP_HOST`
- `IMAP_USER`
- `IMAP_PASSWORD`
- `WEAVE_BASE_EMAIL`
- `WEAVE_ALLOWED_SENDERS`
- a vault root provided by CLI or env

Calendar import also requires:
- Google OAuth token at `$XDG_CONFIG_HOME/wballenthin/weave/token.json`
- Google OAuth client credentials at `$XDG_CONFIG_HOME/wballenthin/weave/credentials.json`

Agent-session import also requires:
- `WEAVE_AGENT_SESSIONS_DIR` or `--agent-sessions` pointing to a directory with `claude/` and/or `pi/` JSONL files

GitHub import also requires:
- `gh` CLI installed and authenticated
- optional `WEAVE_GITHUB_USER` / `--github-user`
- optional `WEAVE_GITHUB_TIMEZONE` / `--github-timezone`

4. Routing behavior

Routes are hardcoded in code. Allowed senders come from `WEAVE_ALLOWED_SENDERS`.

4.1 Voice route
- to-address: `<WEAVE_BASE_EMAIL local-part>+vnote@<WEAVE_BASE_EMAIL domain>`
- writes into `daily/YYYY/MM/DD/transcriptions/`

4.2 reMarkable route
- to-address: `<WEAVE_BASE_EMAIL local-part>+rm2@<WEAVE_BASE_EMAIL domain>`
- writes into `daily/YYYY/MM/DD/scans/`
- stores attachments in `daily/YYYY/MM/DD/_attachments/`

4.3 TODO route
- to-address: `<WEAVE_BASE_EMAIL local-part>+todo@<WEAVE_BASE_EMAIL domain>`
- writes into `daily/YYYY/MM/DD/todo/`
- stores attachments in `daily/YYYY/MM/DD/_attachments/`

5. Storage model

All generated/imported Weave content lives under `daily/YYYY/MM/DD/`.

Per-day layout:
- `_attachments/`
- `_weave/github activity.md`
- `YYYY-MM-DD weave.md`
- `agent sessions/`
- `meeting notes/`
- `transcriptions/`
- `scans/`
- `todo/`

The human-owned personal daily note path is controlled by `.obsidian/daily-notes.json`. The recommended Obsidian configuration is:
- `folder: daily`
- `format: YYYY/MM/DD/YYYY-MM-DD`

6. Imported/generated note behavior

6.1 Voice handler output
- note path: `daily/YYYY/MM/DD/transcriptions/<HHMM> - transcription.md`
- attachment path: `daily/YYYY/MM/DD/_attachments/<HHMM> - <filename>`
- the note includes frontmatter `type: transcript` and `summary`
- attachment embeds are written as relative links from `transcriptions/` to `_attachments/`

6.2 reMarkable handler output
- pdf path: `daily/YYYY/MM/DD/_attachments/<HHMM> - <stem>.pdf`
- note path: `daily/YYYY/MM/DD/scans/<HHMM> - <stem>.md`
- the note includes frontmatter `type: handwriting`, `summary`, and `attachment`
- the OCR/transcription body is wrapped in:
  - `<!-- weave:transcription:start -->`
  - `<!-- weave:transcription:end -->`
- on transcription failure, Weave still writes an error note and marks the message as seen

6.3 TODO handler output
- note path: `daily/YYYY/MM/DD/todo/<HHMM> - <sanitized-subject>.md`
- attachment path: `daily/YYYY/MM/DD/_attachments/<HHMM> - <filename>`
- the note includes frontmatter `type: todo` and `summary`, plus a `## <subject>` heading

6.4 Calendar scraper output
- note path: `daily/YYYY/MM/DD/meeting notes/<HHMM> - <sanitized-event-name>.md`
- Gemini variants use `(<Gemini>)` suffix as before
- chat transcripts use `(chat)` suffix as before
- frontmatter includes `summary`, `source`, `type`, calendar/event metadata, and attendees
- `import calendar --days N` controls the backfill window
- file existence still acts as the cache key

6.5 Agent session scraper output
- note path: `daily/YYYY/MM/DD/agent sessions/<session-id>.md`
- frontmatter: `type`, compact `summary`, `agent`, `project`, `session_id`, `session_sha256`
- the body summary lives inside a managed `weave:summary` region
- the note body also includes metrics and the full conversation rendered as callouts
- frontmatter `summary` is intended for dense daily-note rendering and targets about 12 words
- sync state is tracked in `$XDG_CACHE_HOME/wballethin/weave/agent-session-manifest.json`

6.6 GitHub activity import
- GitHub import writes a snapshot file at `daily/YYYY/MM/DD/_weave/github activity.md`
- `YYYY-MM-DD weave.md` copies that snapshot verbatim into the managed `## GitHub activity` section
- the imported body is the compact repository-summary format
- Weave never imports the current local day
- Weave only imports a completed day after the 6-hour stabilization window in the configured local timezone
- once imported, the day is tracked in `$XDG_CACHE_HOME/wballethin/weave/github-activity-manifest.json`
- import is still best-effort and limited by the recent GitHub user-events feed window

7. Daily note integration

- Weave-generated daily note path is fixed at `daily/YYYY/MM/DD/YYYY-MM-DD weave.md`
- the personal daily note contains only a managed embed region:
  - `<!-- weave:daily-embed:start -->`
  - `![[daily/YYYY/MM/DD/YYYY-MM-DD weave.md]]`
  - `<!-- weave:daily-embed:end -->`
- Weave-generated daily notes render sections in this order when non-empty:
  - `## TODOs`
  - `## Meetings`
  - `## Capture`
  - `## Agent sessions`
  - `## GitHub activity`
- each generated section is wrapped in deterministic HTML comment markers
- standard note sections render compact bullets with aliased wiki-links and optional summaries
- agent sessions render as nested project groups with compact summaries and message counts
- Weave rebuilds daily notes from imported notes plus `_weave/github activity.md`
- as a compatibility measure during migration, daily rebuild also reads legacy `sink/YYYY/MM/DD/*.md` files when they still exist
- daily rebuild removes legacy inline `#weave` lines and legacy managed GitHub sections from the personal daily note while preserving all non-Weave content

8. Message visibility behavior

- a successfully handled routed message is marked `\Seen` after imported note writing and daily-note regeneration succeed
- unrouted messages are left unread
- routed messages with disallowed senders are left unread
- reMarkable-routed messages without PDF attachments are left unread

9. Future extension contract

New email workflows should be added as new handler keys plus new hardcoded routes.
