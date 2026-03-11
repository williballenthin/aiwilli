weave

Weave is a single-process email ingress tool for an Obsidian vault. It monitors one IMAP inbox and routes unread emails to handler logic based on the recipient address.

Routes:

- `+vnote` — voice note transcription: saves note with frontmatter and plain-text body, plus audio attachments.
- `+rm2` — reMarkable snapshots: saves PDF attachment, generates transcription via `llm` CLI, writes embed note.
- `+todo` — TODO items: saves note with subject heading, body, and attachment embeds. Appends a `- [ ] TODO` line to the daily note.

All handlers write into `sink/<YYYY-MM-DD>/` with binary files in `_attachments/`. Generated markdown notes include a `summary` frontmatter property; daily note entries read or backfill that property so one note has one reusable summary. Managed `#weave` lines in daily notes are resynced from linked note summaries once per day.

Required environment variables:

- `IMAP_HOST`
- `IMAP_USER`
- `IMAP_PASSWORD`
- `WEAVE_BASE_EMAIL` — base mailbox address (e.g. `name@example.com`)
- `WEAVE_ALLOWED_SENDERS` — comma-separated list of allowed sender addresses

Run once:

```bash
uv --directory weave run weave /path/to/obsidian-vault --once
```

Run daemon:

```bash
uv --directory weave run weave /path/to/obsidian-vault
```

Agent session imports are cached via a JSON manifest at
`$XDG_CACHE_HOME/wballethin/weave/agent-session-manifest.json`
(falling back to `~/.cache/...`). Session notes are named with the session ID,
store `session_id` and `session_sha256` in front matter, and treat source files
modified within the last 7 days as mutable.

Development checks:

```bash
uv --directory weave run ruff check
uv --directory weave run mypy src tests
uv --directory weave run pytest
```
