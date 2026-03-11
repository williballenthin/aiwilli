Weave specification

Status: draft
Last updated: 2026-03-09

1. Purpose

Weave monitors one IMAP inbox and routes unread emails to handler logic based on the recipient address. It also scrapes Google Calendar meeting notes and chat transcripts on a recurring schedule.

2. Invocation

Command:
- `weave <vault_root> [--poll-interval N] [--once] [--verbose] [--quiet] [--source TAG] [--no-calendar]`

Behavior:
- `--once` processes one unread batch plus one calendar scrape, then exits.
- default mode stays connected and loops with IMAP IDLE; calendar scraper runs in a background thread every 5 minutes.
- `<vault_root>` must exist.
- `--source TAG` sets the calendar source tag in front matter (default: `@hex-rays.com`).
- `--no-calendar` disables the calendar scraper entirely.

3. Required runtime environment

- `IMAP_HOST`
- `IMAP_USER`
- `IMAP_PASSWORD`
- `WEAVE_BASE_EMAIL` (base mailbox, e.g. `name@example.com`)
- `WEAVE_ALLOWED_SENDERS` (comma-separated list of email addresses allowed to send to any route)

For calendar scraping (unless `--no-calendar`):
- Google OAuth token at `$XDG_CONFIG_HOME/wballenthin/weave/token.json` (created via `scripts/setup_google_credentials.py`)
- Google OAuth client credentials at `$XDG_CONFIG_HOME/wballenthin/weave/credentials.json`

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

5.5 Daily note embedding
- for each newly written sink markdown note (from any handler), Weave appends an embed line to the corresponding daily note.
- daily note date uses the event/email timestamp date.
- appended line format: `- HH:MM ![[<vault-relative-note-path>]]`
- daily note folder is loaded from `<vault_root>/.obsidian/daily-notes.json` key `folder`.
- if the daily-notes config file is missing/invalid or folder is empty, Weave uses `<vault_root>/` as daily note folder.
- duplicate embed lines are not appended.
- daily note file I/O is thread-safe (calendar thread and IMAP thread share the writer).

6. Message visibility behavior

- a successfully handled routed message is marked `\\Seen` after sink-note writing and daily-note embed updates succeed.
- unrouted messages are left unread.
- routed messages with disallowed senders are left unread.
- reMarkable-routed messages without PDF attachments are left unread.

- TODO handler daily note lines use `- [ ] TODO: <subject> [[path]]` instead of the standard embed format.
- duplicate TODO lines are not appended.

7. Future extension contract

New email workflows should be added as new handler keys plus new hardcoded routes.
