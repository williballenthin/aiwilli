Margin specification

Status: draft
Last updated: 2026-03-15

1. Purpose

Margin is a local-first code review workspace for browsing a repository snapshot, attaching persistent review comments to code locations, and exporting the findings as an agent-friendly markdown document.

The primary use case is solo review of a full repository snapshot, not pull-request review and not collaborative discussion.

2. Invocation

Commands:
- `margin build <path> --output <review.html> [options]`
- `margin build-github <owner>/<repo> --output <review.html> [options]`
- `margin serve <path> [options]`
- `margin serve-github <owner>/<repo> [options]`

Shared options:
- `--title <title>` overrides the review title
- `--open` opens the generated review in the default browser
- `--verbose` enables debug logging and tracebacks
- `--quiet` reduces logging to errors only

Build command behavior:
- `--output <review.html>` is required
- successful commands print the written HTML path to stdout

GitHub command behavior:
- `--ref <ref>` checks out a specific branch, tag, or commit before snapshot generation

Serve command behavior:
- `--host <host>` sets the HTTP bind host and defaults to `127.0.0.1`
- `--port <port>` sets the HTTP bind port and defaults to `5174`
- `--output-dir <dir>` optionally keeps the generated `review.html` in a persistent directory before serving it
- without `--output-dir`, Margin uses a temporary directory for the served artifact
- successful serve commands print the served review URL to stdout and keep running until interrupted

3. Required runtime environment

Local path mode requires:
- Python runtime for the `margin` CLI
- `git` installed when reviewing a git repository and when GitHub mode is used internally

GitHub mode also requires:
- `gh` CLI installed and authenticated
- repository read access through the current `gh` login

4. Input sources

4.1 Local path mode
- input is a local directory path
- if the directory is a git repository root, Margin uses the current working tree snapshot and records the current `HEAD` commit SHA as the snapshot identifier
- if the directory is not a git repository root, Margin still generates a review from the directory contents and uses a deterministic content hash as the snapshot identifier

4.2 GitHub mode
- input is a GitHub repository identifier like `owner/repo`
- Margin uses authenticated `gh` access to create a temporary checkout, including private repositories when the current `gh` login can read them
- if `--ref` is given, Margin reviews that ref; otherwise it reviews the repository default branch
- the temporary checkout is internal implementation detail and is not part of the exported review artifact

5. Output artifacts

5.1 Static artifact
Margin generates one self-contained HTML file.

The file contains:
- repository metadata
- the selected snapshot identifier
- the complete rendered review UI
- inline CSS and JavaScript
- embedded code content for all included files

The artifact is usable without a server after generation.

5.2 Served artifact
Serve commands generate the same static HTML artifact and then expose it over a lightweight local HTTP server.

6. Repository inclusion rules

- binary files are excluded
- git administrative files are excluded
- common cache and build directories may be excluded by default
- local git repositories respect git ignore rules for untracked files
- Margin is optimized for small to medium repositories that can be embedded into one HTML artifact

7. Review model

7.1 Snapshot scope
- each review is tied to exactly one snapshot
- comments are only guaranteed to remain valid for that exact snapshot
- Margin does not attempt to migrate comments across changed code in the first version

7.2 Comment scopes
Margin supports three comment scopes:
- repository comment
- file comment
- line-range comment

7.3 Comment identity
- each comment has a stable review-local identifier such as `RV-001`
- identifiers persist through local autosave and JSON export/import within the same snapshot

7.4 Comment content
Each comment stores:
- identifier
- scope
- file path when applicable
- start and end line when applicable
- optional excerpt captured from the reviewed code
- optional title
- required body text
- creation and update timestamps

8. Review UI behavior

8.1 Desktop layout
The generated HTML presents three primary areas:
- a left file browser tree
- a central code pane
- a right review sidebar

8.2 Mobile layout
The generated HTML supports full review authoring on iPhone-sized screens.

The mobile layout uses an explicit panel switcher with Files, Code, and Comments views. Users can still:
- navigate files
- select line ranges
- create, edit, and delete comments
- mark files reviewed
- export markdown and JSON
- use comment presets

8.3 File browser behavior
- shows repository folders and files
- shows comment counts per file
- shows whether a file has been marked reviewed
- supports filtering by file path text
- supports filtering to commented files only
- supports filtering to unreviewed files only

8.4 Code pane behavior
- shows one file at a time
- shows syntax-highlighted code and line numbers
- keeps syntax colors and code surfaces aligned with the document light or dark theme rather than using a fixed standalone code background
- shows existing comment markers and highlighted commented ranges
- supports line-based range selection by choosing a start line and an end line
- supports file-level review actions such as adding a file comment and marking the file reviewed

8.5 Sidebar behavior
- shows the active comment composer
- shows browser-local comment presets and lets the user add or delete presets
- shows repository comments plus comments relevant to the current file
- supports editing and deleting existing comments

9. Persistence behavior

9.1 Local autosave
- review state is automatically stored in browser local storage
- the storage key is derived from the snapshot identifier
- reopening the same HTML artifact restores the saved review state for that snapshot on that browser

9.2 Preset storage
- comment presets are stored in browser local storage
- presets are browser-local and not tied to one snapshot

9.3 Review import/export
- users can export the current review state as JSON
- users can import a previously exported JSON review state into the same snapshot
- JSON import into a different snapshot is rejected

10. Markdown export

The generated review UI supports download of a markdown report containing open comments only.

The markdown report includes:
- review metadata
- a summary section with comment counts by scope
- reviewed file listing when present
- a findings index
- detailed comment sections grouped by repository scope and file path

Each exported comment includes:
- the stable comment identifier
- scope
- file path and line range when applicable
- title when present
- body text
- excerpt when present
- creation and update timestamps

The markdown is intended to be directly pasted into or referenced from a coding-agent session.

11. Search behavior

Margin does not provide repository-wide application search in the first version.

Expected search behavior:
- browser find works on whatever content is currently visible in the document
- Margin does not promise cross-file search beyond that visible content behavior

12. Out of scope for first version

- threaded discussions
- collaborative multi-user review
- code suggestion blocks or patch application
- symbol-aware or AST-aware anchors
- comment migration across snapshots
- repository-wide full-text search beyond visible browser content
