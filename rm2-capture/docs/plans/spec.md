# rm2-capture Specification

A daemon that monitors an email inbox for Remarkable 2 PDF exports, transcribes handwritten notes using an LLM, and saves them as markdown files.

## Purpose

Capture handwritten notes from a Remarkable 2 tablet into a local notes directory. The Remarkable's built-in "email page" feature sends PDFs to a designated email address. This daemon monitors that inbox, downloads PDFs, performs OCR transcription via LLM, and writes structured markdown files.

## Goals

- **Automated capture**: No manual intervention required after initial setup
- **Real-time processing**: Notes appear in the output directory within seconds of sending
- **Preserve originals**: Keep source PDFs alongside transcriptions for reference
- **Hackable**: Simple, readable code that's easy to modify and extend
- **Robust**: Handle connection drops, LLM failures, and restarts gracefully

## Non-Goals

- Obsidian-specific features (just writes to a directory)
- GUI or web interface
- Database or persistent state beyond the filesystem
- Processing non-PDF attachments
- Bi-directional sync

## Output Structure

All output is written to a single directory specified at startup.

```
output_dir/
  2026-01-26/
    11:30 - Meeting notes - page 1.md
    14:45 - 2026 - page 122.md
    _attachments/
      Meeting notes - page 1.pdf
      2026 - page 122.pdf
  2026-01-27/
    09:00 - Ideas - page 1.md
    _attachments/
      Ideas - page 1.pdf
```

### Folder naming

Date folders use ISO format: `YYYY-MM-DD`, derived from the email's received timestamp.

### File naming

Markdown files: `{HH:MM} - {pdf_stem}.md`
- `HH:MM` is the email received time (24-hour format)
- `pdf_stem` is the PDF filename without extension

PDF files are stored with their original filename in the `_attachments/` subdirectory.

### Markdown file format

```markdown
---
subject: "Email subject line"
attachment: "Meeting notes - page 1.pdf"
received: 2026-01-26T11:30:00
transcribed: 2026-01-26T11:31:15
---

![[_attachments/Meeting notes - page 1.pdf]]

[transcribed content here]
```

Frontmatter fields:
- `subject`: Original email subject
- `attachment`: Original PDF filename
- `received`: Email received timestamp (ISO 8601)
- `transcribed`: When transcription completed (ISO 8601)

The PDF embed uses Obsidian's wiki-link syntax but this is purely cosmetic; the daemon has no Obsidian-specific logic.

### Error file format

When transcription fails, the markdown file contains:

```markdown
---
subject: "Email subject line"
attachment: "Meeting notes - page 1.pdf"
received: 2026-01-26T11:30:00
error: "No markdown code block found in response"
---

![[_attachments/Meeting notes - page 1.pdf]]

<!-- TRANSCRIPTION_FAILED: No markdown code block found in response -->
```

The PDF is still saved. The error is recorded in both frontmatter and an HTML comment for visibility.

## Email Monitoring

### Connection

Connects to an IMAP server using provided credentials. Maintains a persistent connection with automatic reconnection on failure.

### Real-time notifications

Uses IMAP IDLE extension for instant notification of new emails. Falls back to polling at a configurable interval if IDLE times out or the connection drops.

### Startup behavior

On startup, processes all existing unread emails that match filters before entering the IDLE loop. This catches up after downtime.

### Filtering

Emails must pass ALL filters to be processed:

1. **Unread**: Only UNSEEN emails are fetched
2. **TO address**: Recipient must exactly match `FILTER_TO_ADDRESS`
3. **Sender allowlist**: Sender must be in `ALLOWED_SENDERS` list
4. **Has PDF attachments**: Email must contain at least one PDF attachment

Emails that don't match filters are ignored (left unread).

### Mark as read

After successfully processing all attachments from an email (regardless of transcription success/failure), the email is marked as read.

## Duplicate Detection

Two-stage detection prevents reprocessing:

1. **IMAP level**: Only unread emails are fetched
2. **Filesystem level**: Skip attachments where the PDF already exists in `_attachments/`

If a PDF exists but the markdown file doesn't (e.g., deleted for re-transcription), the attachment is skipped. To force reprocessing, delete both the PDF and markdown file, then mark the email as unread.

## Transcription

### LLM invocation

Uses the `llm` CLI tool (pre-installed and configured) to invoke Gemini:

```
llm -m gemini/gemini-3-flash-preview -a <pdf_path> "<prompt>"
```

The model is hardcoded to `gemini/gemini-3-flash-preview`.

### Prompt

The prompt requests verbatim transcription with structure preservation:

```
Transcribe this handwritten note verbatim. Output ONLY a single markdown
code block containing the transcription. Preserve the structure including:
- Bullet points and indentation
- Tables (as markdown tables)
- Line breaks and paragraphs

Do not add any commentary, analysis, or text outside the code block.
```

### Response parsing

Expects exactly one markdown code fence in the response. Extracts content between the first ``` and closing ```. Fails if no fence is found.

### Error handling

Transcription can fail due to:
- `llm` CLI not found or exits non-zero
- Network/API errors from Gemini
- Response doesn't contain a markdown code block

On failure:
- PDF is still saved to `_attachments/`
- Markdown file is created with error placeholder
- Email is marked as read
- Processing continues with next attachment

## Configuration

### Environment variables (required)

| Variable | Description |
|----------|-------------|
| `IMAP_HOST` | IMAP server hostname (e.g., `imap.gmail.com`) |
| `IMAP_USER` | Email account username |
| `IMAP_PASSWORD` | Email account password or app-specific password |
| `FILTER_TO_ADDRESS` | Required recipient address (e.g., `user+remarkable@gmail.com`) |
| `ALLOWED_SENDERS` | Comma-separated list of allowed sender addresses |

All environment variables are required. The daemon exits with an error if any are missing.

### Command-line arguments

```
rm2-capture [OPTIONS] OUTPUT_DIR

Arguments:
  OUTPUT_DIR            Directory to write notes

Options:
  --poll-interval INT   Fallback polling interval in seconds (default: 300)
  --verbose            Enable debug logging
  --quiet              Only show errors
```

## User Interface

### Output

Simple logging to stderr via Rich's logging handler. No progress bars or spinners.

Example output:
```
Connected to imap.gmail.com as user@gmail.com
Found 2 emails with 3 attachments
Processing Notes - page 1.pdf
Saved PDF to /path/2026-01-26/_attachments/Notes - page 1.pdf
Transcribing Notes - page 1.pdf...
Created note: /path/2026-01-26/11:30 - Notes - page 1.md
```

### Logging

- Default: INFO level, shows processing activity
- `--verbose`: DEBUG level, includes detailed diagnostics
- `--quiet`: ERROR level, only shows failures

### Signals

- `SIGINT` (Ctrl+C): Immediate exit
- `SIGTERM`: Immediate exit

## Guarantees

### Atomicity

PDF is written before markdown file. If the process crashes mid-operation:
- If PDF doesn't exist: nothing was written, email still unread, will retry
- If PDF exists but no markdown: email marked as read, can manually re-run transcription

### Idempotency

Running the daemon multiple times against the same inbox produces the same output. Already-processed emails (read + PDF exists) are skipped.

### No data loss

- Original PDFs are always preserved
- Transcription failures don't prevent PDF storage
- Errors are recorded in the output file, not silently dropped

## Future Considerations

These are explicitly out of scope for initial implementation but the design accommodates them:

- **Re-transcription command**: Find error placeholder files and re-run transcription
- **Different LLM models**: Could be made configurable via env var
- **Multiple output formats**: The writer could be extended
- **Web hook notifications**: Could notify on new notes
