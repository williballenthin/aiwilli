weave

Weave is a single-process email ingress tool for an Obsidian vault.

It replaces two standalone scripts:
- `scripts/vnote-pipe-obsidian.py`
- `scripts/rm2-pipe-obsidian.py`

Current handlers:
- voice note transcription emails to `<base-local>+vnote@<domain>`
- reMarkable snapshot emails to `<base-local>+rm2@<domain>`

Both handlers write into the vault at `sink/<YYYY-MM-DD>/` and use `_attachments/` for binary files.

The routing variants are hardcoded in `src/weave/app.py`. This is intentional for personal use.

Required environment variables:
- `IMAP_HOST`
- `IMAP_USER`
- `IMAP_PASSWORD`
- `WEAVE_BASE_EMAIL`

Run once:

```bash
uv --directory weave run weave /path/to/obsidian-vault --once
```

Run daemon:

```bash
uv --directory weave run weave /path/to/obsidian-vault
```

Development checks:

```bash
uv --directory weave run ruff check
uv --directory weave run mypy src tests
uv --directory weave run pytest
```
