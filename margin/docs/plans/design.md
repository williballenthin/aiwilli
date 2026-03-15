Margin design

Status: draft
Last updated: 2026-03-15

1. Code layout

Planned module layout:
- `src/margin/cli.py`: argparse entrypoint, logging setup, browser opening, command dispatch
- `src/margin/app.py`: top-level build orchestration for local and GitHub sources
- `src/margin/models.py`: Pydantic models for snapshots, files, and build configuration
- `src/margin/sources.py`: local directory scanning and optional GitHub temporary checkout helpers
- `src/margin/render.py`: syntax highlighting, snapshot JSON embedding, and self-contained HTML rendering
- `src/margin/templates/review.html.j2`: inline HTML, CSS, and JavaScript UI template
- `tests/`: CLI, scanning, and rendering tests

2. Build pipeline

The first implementation uses an offline build pipeline:
1. resolve the requested source
2. create a normalized snapshot model
3. render the snapshot into one static HTML document
4. optionally open the output in a browser

The browser session owns mutable review state. Python only produces the snapshot artifact.

3. Source resolution

3.1 Local directory source
- resolve the input path
- determine whether it is a git repository root
- if it is a git root, gather files via git-aware enumeration so ignore rules are respected
- otherwise walk the filesystem directly with a small default exclude set

3.2 GitHub source
- create a temporary working directory
- run `gh repo clone` into that directory
- use a shallow checkout and optional `--ref` branch selection
- render the temporary checkout exactly like a local directory source
- discard the checkout after rendering

GitHub support is intentionally implemented as a preprocessing step rather than browser-side fetching. This avoids auth, CORS, and API pagination concerns inside the generated HTML.

4. Snapshot model

Planned Pydantic models:
- `FileSnapshot`: relative path, language label, line count, syntax-highlighted HTML lines, content digest
- `ReviewSnapshot`: source kind, source label, review title, snapshot identifier, generated timestamp, files
- `BuildRequest`: source description, output path, optional ref, title override, browser-open flag

Snapshot identifiers:
- git sources use `HEAD` commit SHA
- non-git sources use a deterministic hash of included file paths and content digests

5. File processing

For each included file:
- read bytes
- skip files that appear binary or exceed size limits
- decode as text
- choose a Pygments lexer from filename when possible, otherwise plain text
- render syntax-highlighted HTML with line granularity suitable for client-side line selection

The snapshot keeps one highlighted HTML string per rendered line. This keeps the browser renderer simple and avoids client-side lexing.

6. HTML rendering strategy

The generated document is fully self-contained.

Rendering pieces:
- metadata header and controls
- embedded snapshot JSON inside a non-executing script tag
- inline CSS for layout, typography, and syntax highlighting
- inline JavaScript for navigation, comment editing, persistence, and export

The snapshot JSON must escape `</script>`-like sequences so source code cannot terminate the embedding script element.

7. Browser UI state model

Client-side mutable state is stored as JSON with fields similar to:
- `snapshotId`
- `nextSequence`
- `reviewedFiles`
- `comments`
- `updatedAt`

Each comment stores:
- `id`
- `scope`
- `path`
- `startLine`
- `endLine`
- `excerpt`
- `title`
- `body`
- `createdAt`
- `updatedAt`

The browser loads state in this order:
1. explicit imported JSON when the user chooses import
2. previously autosaved local-storage state for the same snapshot
3. empty default state

8. DOM strategy

The HTML artifact embeds all files as data, but the code pane mounts one file at a time.

Reasoning:
- keeps the active DOM smaller than rendering every syntax-highlighted line at once
- still preserves the self-contained single-file artifact model
- accepts that browser find only works on currently visible content

The file tree is rendered as nested folders using `details` and `summary` elements.

9. Interaction model

Line-range comments are created by selecting start and end lines rather than arbitrary text spans.

Reasoning:
- simpler implementation
- more robust on mobile Safari and touch input
- stable enough for review export anchored by line range plus excerpt

The right sidebar contains one comment composer used for:
- repository comments
- file comments
- range comments
- editing existing comments

10. Export behavior

Markdown export is generated in the browser from the current state and includes only open comments.

JSON export is the canonical persisted state and is also generated in the browser.

Python does not post-process review state after the artifact is built.

11. Logging and CLI behavior

- `cli.py` configures Rich logging to stderr
- stdout is reserved for command output and user-facing error lines
- `--verbose` enables debug logging and tracebacks
- `--quiet` reduces logging verbosity
- longer steps such as GitHub checkout and repository scan use transient spinner status output on stderr

12. Test strategy

Initial tests should cover:
- git-aware file enumeration and ignore behavior
- non-git directory snapshot hashing
- HTML rendering and safe JSON embedding
- CLI build flow writing an output artifact
- GitHub clone command construction without requiring network access

The test suite should stay filesystem-oriented and avoid mocks.
