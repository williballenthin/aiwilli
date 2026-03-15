Margin design

Status: draft
Last updated: 2026-03-15

1. Code layout

Current module layout:
- `src/margin/__main__.py`: module entrypoint
- `src/margin/cli.py`: argparse entrypoint, Rich logging setup, command dispatch, and serve-mode orchestration
- `src/margin/app.py`: top-level build orchestration and output writing
- `src/margin/models.py`: Pydantic models for source files and snapshots
- `src/margin/sources.py`: local directory scanning, git-aware enumeration, snapshot hashing, and GitHub temporary checkout helpers
- `src/margin/render.py`: syntax highlighting, review-data preparation, safe JSON embedding, and HTML rendering
- `src/margin/server.py`: lightweight HTTP serving helpers for generated review artifacts
- `src/margin/templates/review.html.j2`: inline HTML, CSS, and JavaScript UI template
- `tests/test_app.py`: local build orchestration test
- `tests/test_cli.py`: CLI parser and build flow tests
- `tests/test_render.py`: HTML embedding and UI-presence tests
- `tests/test_server.py`: real HTTP serving test
- `tests/test_sources.py`: git-aware enumeration, hashing, and GitHub command tests

2. Build pipeline

Margin uses an offline snapshot pipeline:
1. resolve the requested source
2. create a normalized snapshot model
3. render the snapshot into one static HTML document
4. optionally open the document directly in a browser or serve it over local HTTP

The browser session owns mutable review state. Python only produces or serves the snapshot artifact.

3. Source resolution

3.1 Local directory source
- resolve the input path
- determine whether it is a git repository root
- if it is a git root, gather files via `git ls-files --cached --others --exclude-standard -z` so ignore rules are respected
- otherwise walk the filesystem directly with a small default exclude set plus an optional root `.gitignore` pathspec

3.2 GitHub source
- create a temporary working directory
- run `gh repo clone <repo> <dir> -- --depth=1`
- if `--ref` is provided, run `git fetch --depth=1 origin <ref>` followed by `git checkout --detach FETCH_HEAD`
- render the temporary checkout exactly like a local directory source
- discard the checkout after rendering

GitHub support is implemented as a preprocessing step rather than browser-side fetching. This avoids auth, CORS, and API pagination concerns inside the generated HTML.

4. Snapshot model

Implemented Python-side models:
- `SourceFile`: relative path, decoded text, content digest
- `SourceSnapshot`: source kind, source label, review title, snapshot identifier, generated timestamp, files

Request/result dataclasses in `app.py`:
- `LocalBuildRequest`
- `GitHubBuildRequest`
- `BuildResult`

The browser-side review payload is built in `render.py` as a plain JSON object containing rendered files with:
- path
- language
- line count
- syntax-highlighted HTML lines
- content digest

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

6. Local server flow

`server.py` provides the small HTTP-serving layer used by `margin serve` and `margin serve-github`:
- `create_http_server()` builds a `ThreadingHTTPServer` rooted at a directory
- `run_http_server()` serves until interrupted
- `start_http_server()` exists for tests and starts the same server in a background thread
- `build_review_url()` generates the browser URL for the served artifact and normalizes `0.0.0.0` to `127.0.0.1` for browser use

Serve commands write `review.html` into either:
- a caller-specified `--output-dir`, or
- a temporary directory owned by `ExitStack`

The HTTP server serves the artifact directory directly. There is no separate app server, API, or runtime state on the Python side.

7. HTML rendering strategy

The generated document is fully self-contained.

Rendering pieces:
- metadata header and compact controls
- embedded snapshot JSON inside a non-executing script tag
- inline CSS for layout, typography, contextual panes, inline comment cards, and syntax highlighting
- inline JavaScript for navigation, comment editing, persistence, pane toggling, and export

`render.py` uses a custom Pygments style backed by CSS variables so syntax token colors and code-surface backgrounds follow the document light and dark theme without introducing fixed white code blocks.

The snapshot JSON must escape `</script>`-like sequences so source code cannot terminate the embedding script element.

8. Browser state model

Client-side mutable review state is stored as JSON with fields:
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

The browser UI no longer exposes title editing, but the field remains in normalized state for backward-compatible import and export of older review JSON.

The browser loads review state in this order:
1. explicit imported JSON when the user chooses import
2. previously autosaved local-storage state for the same snapshot
3. empty default state

9. DOM and interaction strategy

The HTML artifact embeds all files as data, but the code pane mounts one file at a time.

Reasoning:
- keeps the active DOM smaller than rendering every syntax-highlighted line at once
- still preserves the self-contained single-file artifact model
- accepts that browser find only works on currently visible content

The file tree uses nested `details` and `summary` elements, with filter controls placed behind a compact `details` toggle so the tree can stay near the top of the pane.

Desktop layout is a two-column grid by default:
- file browser
- code pane

A third comments pane is only inserted into the desktop grid when the user opens it or starts writing/editing a comment.

Range comments are still created by selecting start and end lines rather than arbitrary text spans.

Reasoning:
- simpler implementation
- more robust on mobile Safari and touch input
- stable enough for review export anchored by line range plus excerpt

Rendered range comments are anchored inline below their end line. File comments render in a note stack above the current file only when they exist. This keeps comments visually attached to the code without permanently reserving a right sidebar.

The code pane uses one horizontal scroll surface for the whole file. Individual lines no longer own their own horizontal scroll container.

On narrow screens, the document switches to an explicit Files / Code / Comments panel model. The JavaScript moves the user to the most likely panel for the current action, for example:
- selecting a file opens Code
- finishing a line-range selection opens Comments
- editing a comment opens Comments
- focusing a range comment opens Code and scrolls to the anchor line

10. Export behavior

Markdown export is generated in the browser from the current state and includes only open comments.

The markdown export includes:
- top-level metadata
- summary counts
- reviewed-file list
- findings index
- grouped detailed sections

JSON export is the canonical persisted review state and is also generated in the browser.

Python does not post-process review state after the artifact is built.

11. Logging and CLI behavior

- `cli.py` configures Rich logging to stderr
- stdout is reserved for command output and user-facing error lines
- build commands print the output artifact path
- serve commands print the served URL, then block in the HTTP server until interrupted
- `--verbose` enables debug logging and tracebacks
- `--quiet` reduces logging verbosity
- longer build steps use `rich.live.Live` with `Spinner(..., transient=True)` on stderr

12. Test strategy

Current tests cover:
- git-aware file enumeration and ignore behavior
- non-git directory snapshot hashing
- HTML rendering and safe JSON embedding
- presence of mobile navigation and contextual note UI in rendered output
- local app build flow writing an output artifact
- CLI parser/build behavior
- real local HTTP serving of a generated artifact
- GitHub clone/fetch/checkout command construction without requiring network access

The test suite stays filesystem-oriented and avoids mocks.
