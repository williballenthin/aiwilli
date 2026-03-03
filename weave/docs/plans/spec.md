Weave specification

Status: draft
Last updated: 2026-03-03

1. Purpose

Weave monitors one IMAP inbox and routes unread emails to handler logic based on the recipient address.

2. Invocation

Command:
- `weave <vault_root> [--poll-interval N] [--once] [--verbose] [--quiet]`

Behavior:
- `--once` processes one unread batch and exits.
- default mode stays connected and loops with IMAP IDLE.
- `<vault_root>` must exist.

3. Required runtime environment

- `IMAP_HOST`
- `IMAP_USER`
- `IMAP_PASSWORD`
- `WEAVE_BASE_EMAIL` (base mailbox, e.g. `name@example.com`)

4. Routing behavior

Routing is hardcoded in code. The base mailbox comes from `WEAVE_BASE_EMAIL`; variants (`+vnote`, `+rm2`) are hardcoded.

4.1 Voice route
- to-address: `<WEAVE_BASE_EMAIL local-part>+vnote@<WEAVE_BASE_EMAIL domain>`
- allowed sender: `wilbal1087@gmail.com`
- output root: `<vault_root>/sink/`

4.2 reMarkable route
- to-address: `<WEAVE_BASE_EMAIL local-part>+rm2@<WEAVE_BASE_EMAIL domain>`
- allowed sender: `my@remarkable.com`
- output root: `<vault_root>/sink/`

5. Output behavior

5.1 Voice handler output
- note path: `<output>/<YYYY-MM-DD>/<HHMM> - transcription.md`
- attachment path: `<output>/<YYYY-MM-DD>/_attachments/<HHMM> - <filename>`
- note contains frontmatter and the email plain-text body.

5.2 reMarkable handler output
- saved pdf: `<output>/<YYYY-MM-DD>/_attachments/<HHMM> - <stem>.pdf`
- note path: `<output>/<YYYY-MM-DD>/<HHMM> - <stem>.md`
- note contains embed link to saved PDF.
- transcription is generated through the `llm` CLI against model `gemini/gemini-3-flash-preview`.
- on transcription failure, Weave still writes an error note and marks the message as seen.

6. Message visibility behavior

- a successfully handled routed message is marked `\\Seen`.
- unrouted messages are left unread.
- routed messages with disallowed senders are left unread.
- reMarkable-routed messages without PDF attachments are left unread.

7. Future extension contract

New email workflows should be added as new handler keys plus new hardcoded routes.
