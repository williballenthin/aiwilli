Weave design

Status: draft
Last updated: 2026-03-03

1. Module layout

- `src/weave/app.py`: all runtime logic for now.
- `tests/test_app.py`: route and handler tests.

2. Core types

- `WeaveConfig` (Pydantic): runtime config loaded from env + CLI args with hardcoded route variants.
- `RouteConfig` (Pydantic): route metadata (`to_address`, `allowed_senders`, `handler_key`, sink path).
- `get_variant_address(base_email, variant)`: derives `local+variant@domain` from `WEAVE_BASE_EMAIL`.
- `IncomingMessage` (dataclass): normalized unread message from IMAP.
- `Attachment` (dataclass): decoded email attachment.
- `HandlerResult` (dataclass): whether the message was handled and which files were written.

3. Runtime flow

1. Parse CLI args.
2. Build `WeaveConfig` from env and hardcoded route variants (`+vnote`, `+rm2`) resolved from `WEAVE_BASE_EMAIL`; route sink path is `sink/` under vault root.
3. Connect with `IMAPClient` and select `INBOX`.
4. Fetch unread messages with envelope + RFC822 payload.
5. Normalize sender/to-addresses and resolve route.
6. Dispatch to handler by `handler_key`.
7. If handler result says handled, mark message as seen.
8. In daemon mode, enter IMAP IDLE and repeat on notifications.

4. Handler implementations

4.1 `VoiceNoteHandler`
- extracts text/plain body from multipart email
- extracts all attachment parts marked `attachment`
- writes date folder + `_attachments`
- writes one markdown note with YAML frontmatter and Obsidian attachment embeds

4.2 `RemarkableSnapshotHandler`
- extracts `application/pdf` attachments
- writes each PDF file under `_attachments`
- asks `PdfTranscriber` for markdown transcription
- writes markdown note with embed and transcription
- writes failure note when transcription throws `TranscriptionError`

5. Transcription abstraction

- protocol: `PdfTranscriber.get_transcription(pdf_path) -> str`
- concrete: `LlmPdfTranscriber` that shells out to `llm`
- tests use deterministic in-memory transcriber classes without mocks

6. Consolidation notes from previous scripts

The old standalone scripts had duplicated blocks for:
- IMAP connection lifecycle
- unread message scanning
- envelope decoding
- date-folder note writing
- long-running loop and reconnect

Weave keeps one monitor/loop and routes to specialized handlers. The previous per-script behavior is preserved for naming and markdown output shape.

7. Planned next refactors

- split `app.py` into `mailbox.py`, `routes.py`, `handlers/`, and `cli.py`
- add handler for links/todos/quick notes
- add route-level metrics and structured JSON run report
