weave

Weave is a single-process email ingress and activity import tool for an Obsidian vault.

Implemented workflows:
- IMAP email routing into sink notes
- Google Calendar meeting note/chat export
- AI agent session import from Claude Code and Pi JSONL logs
- GitHub activity import into daily notes

Storage model:
- sink notes live under `sink/YYYY/MM/DD/`
- attachments live under `sink/YYYY/MM/DD/_attachments/`
- Weave-generated daily notes live under `weave/daily/YYYY/MM/DD/YYYY-MM-DD.md`
- personal daily notes keep only a managed embed of the matching Weave daily note

Email routes:
- `+vnote` — voice note transcription: saves a markdown note plus attachments
- `+rm2` — reMarkable snapshots: saves PDF attachment, transcribes through `llm`, writes embed note
- `+todo` — TODO items: saves a note with subject/body/attachments and renders it in the generated `## TODOs` section

Generated sink notes include a reusable `summary` frontmatter property. Weave backfills that summary when needed and reuses it in generated daily-note sections.

Agent session notes:
- stored in `sink/YYYY/MM/DD/<session-id>.md`
- frontmatter is intentionally minimal: `type`, `summary`, `agent`, `project`, `session_id`, `session_sha256`
- body contains a structured summary, metrics table, and callout-rendered conversation
- sync state lives at `$XDG_CACHE_HOME/wballethin/weave/agent-session-manifest.json`

GitHub activity:
- imported directly into the generated Weave daily note, not as sink notes
- rendered as a compact repository index with counts per activity kind
- finalized days are tracked in `$XDG_CACHE_HOME/wballethin/weave/github-activity-manifest.json`

Required environment variables for normal daemon/once mode:
- `IMAP_HOST`
- `IMAP_USER`
- `IMAP_PASSWORD`
- `WEAVE_BASE_EMAIL`
- `WEAVE_ALLOWED_SENDERS`

Run once:

```bash
uv --directory weave run weave /path/to/obsidian-vault --once
```

Run daemon:

```bash
uv --directory weave run weave /path/to/obsidian-vault
```

Regenerate only the Weave daily notes, without touching sink notes or personal daily notes:

```bash
uv --directory weave run weave /path/to/obsidian-vault --generate-weave-daily-notes-only
```

Regenerate Weave daily notes and clean legacy inline `#weave` content out of personal daily notes:

```bash
uv --directory weave run weave /path/to/obsidian-vault --migrate-daily-notes
```

Regenerate Weave daily notes and also migrate the personal daily-note layout to nested `YYYY/MM/DD/YYYY-MM-DD` paths:

```bash
uv --directory weave run weave /path/to/obsidian-vault \
  --migrate-daily-notes \
  --daily-note-format YYYY/MM/DD/YYYY-MM-DD
```

Development checks:

```bash
uv --directory weave run ruff check
uv --directory weave run mypy src tests
uv --directory weave run pytest
```
