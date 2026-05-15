weave

Weave imports outside activity into an Obsidian vault.

Implemented workflows:
- IMAP email routing into day-local notes
- Google Calendar meeting note/chat export
- AI agent session import from Claude Code and Pi JSONL logs
- GitHub activity snapshots plus daily-note rendering
- Vault file-activity snapshots: markdown files outside `daily/` created or modified on a given day

Storage model:
- Weave writes into `daily/YYYY/MM/DD/`
- attachments live in `daily/YYYY/MM/DD/_attachments/`
- GitHub snapshots live in `daily/YYYY/MM/DD/_weave/github activity.md`
- Vault-activity snapshots live in `daily/YYYY/MM/DD/_weave/vault activity.md`
- Weave-generated daily notes live at `daily/YYYY/MM/DD/YYYY-MM-DD weave.md`
- imported notes live under category subdirectories:
  - `agent sessions/`
  - `meeting notes/`
  - `transcriptions/`
  - `scans/`
  - `todo/`
- the personal daily note path comes from `.obsidian/daily-notes.json`

Email routes:
- `+vnote` — saves a transcription note plus attachments under `transcriptions/`
- `+rm2` — saves a PDF under `_attachments/`, writes a note under `scans/`, and stores the OCR/transcription inside a managed `weave:transcription` region
- `+todo` — saves a note with subject/body/attachments under `todo/`

Agent session notes:
- stored in `daily/YYYY/MM/DD/agent sessions/<session-id>.md`
- frontmatter: `type`, `summary`, `agent`, `project`, `session_id`, `session_sha256`
- body contains a managed `weave:summary` region, metrics table, and callout-rendered conversation
- sync state lives at `$XDG_CACHE_HOME/wballethin/weave/agent-session-manifest.json`

GitHub activity:
- imported into `_weave/github activity.md`
- copied verbatim into the managed `## GitHub activity` section of the generated Weave daily note
- finalized days are tracked in `$XDG_CACHE_HOME/wballethin/weave/github-activity-manifest.json`

Vault file activity:
- scans markdown files outside `daily/`, `sink/`, `.obsidian/`, `.trash/`, and other hidden/dotfile dirs
- buckets each file by both filesystem birth/ctime and mtime into a rolling window of days
- renders one `## Vault activity` section per day listing entries as `created: [[…]]` then `modified: [[…]]`
- snapshot written to `_weave/vault activity.md`; finalized days tracked in `$XDG_CACHE_HOME/wballethin/weave/vault-activity-manifest.json`
- today is omitted; days finalize after a 6-hour stabilization window in the configured local timezone
- `birthtime` is preferred when available (macOS, Linux 4.11+ ext4/btrfs/xfs via `statx`); falls back to `ctime`, which on Unix can bump on chmod/rename — best-effort

Recommended environment variables for deployed monitor/email sync:
- `IMAP_HOST`
- `IMAP_USER`
- `IMAP_PASSWORD`
- `WEAVE_BASE_EMAIL`
- `WEAVE_ALLOWED_SENDERS`
- `WEAVE_VAULT_ROOT` (`OBSIDIAN_VAULT_ROOT` is accepted as a fallback)

Commands:

```bash
uv --directory weave run weave monitor
uv --directory weave run weave sync
uv --directory weave run weave import calendar --days 365
uv --directory weave run weave import agent-sessions
uv --directory weave run weave import github
uv --directory weave run weave import vault-activity --days 7
uv --directory weave run weave rebuild daily
```

Development checks:

```bash
uv --directory weave run ruff check
uv --directory weave run mypy src tests
uv --directory weave run pytest
```
