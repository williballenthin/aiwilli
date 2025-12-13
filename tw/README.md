# tw - SQLite-backed Issue Tracker for AI Agents

`tw` is a command-line issue tracker optimized for AI agent workflows. It uses SQLite for data storage with a hierarchical issue structure (epics → stories → tasks) and provides specialized commands for agent-friendly handoffs, context preservation, and work tracking.

## Features

- **Hierarchical Issues**: Three-level structure (epic/story/task) with stable IDs
- **Status Tracking**: New → In Progress → Blocked/Stopped → Done
- **Agent Handoffs**: Structured handoff protocol for context preservation
- **Rich Annotations**: Typed annotations (lessons, deviations, commits, etc.)
- **Reference Extraction**: Automatic detection and tracking of issue cross-references
- **JSON Output**: Machine-readable output for agent consumption

## Installation

### Prerequisites

- Python 3.11 or higher

### Install from Source

```bash
git clone <repository-url>
cd tw
pip install -e ".[dev]"
```

## Quick Start

### 1. Set Environment Variables

```bash
export TW_PROJECT_NAME="myproject"
export TW_PROJECT_PREFIX="PROJ"
```

### 2. Create Your First Epic

```bash
tw new epic --title "User Authentication"
# Output: Created epic PROJ-1
```

### 3. Create a Story Under the Epic

```bash
tw new story --title "Login Flow" --parent PROJ-1
# Output: Created story PROJ-1-1
```

### 4. Create a Task Under the Story

```bash
tw new task --title "Implement login form" --parent PROJ-1-1
# Output: Created task PROJ-1-1a
```

### 5. Work on the Task

```bash
# Start work
tw start PROJ-1-1a

# Mark as done
tw done PROJ-1-1a --message "Implemented with React form validation"
```

### 6. List All Issues

```bash
tw list
# Output:
# PROJ-1 [new] User Authentication
# PROJ-1-1 [new] Login Flow
# PROJ-1-1a [done] Implement login form
```

### 7. View Issue Details

```bash
tw show PROJ-1-1a
```

## CLI Commands

### Creating Issues

#### `tw new TYPE --title TITLE [OPTIONS]`

Create a new issue of the specified type.

**Arguments:**
- `TYPE`: Issue type (`epic`, `story`, or `task`)

**Options:**
- `--title, -t TEXT`: Issue title (required)
- `--parent, -p ID`: Parent issue ID (optional for epics, required for stories/tasks unless orphan)
- `--body, -b TEXT`: Issue body/description (use `-` to read from stdin)

**Examples:**

```bash
# Create an epic
tw new epic --title "User Management System"

# Create a story under an epic
tw new story --title "Password Reset Flow" --parent PROJ-1

# Create a task under a story with body
tw new task --title "Design reset form" --parent PROJ-1-1 \
  --body "Create a responsive password reset form with email validation"

# Create a task with body from stdin
tw new task --title "Fix bug" --parent PROJ-1-1 --body -
# (then type or paste the body, followed by Ctrl-D)

# Create orphan task (auto-assigned to next epic slot)
tw new task --title "Quick fix for homepage"
```

**ID Generation:**
- **Epics**: `PREFIX-N` (e.g., `PROJ-1`, `PROJ-2`)
- **Stories**: `PREFIX-N-M` (e.g., `PROJ-1-1`, `PROJ-1-2`)
- **Tasks**: `PREFIX-N-Ma` (e.g., `PROJ-1-1a`, `PROJ-1-1b`)

### Viewing Issues

#### `tw list`

List all issues in the current project, sorted by ID.

**Output Format:**
```
PROJ-1 [new] User Authentication
PROJ-1-1 [in_progress] Login Flow
PROJ-1-1a [done] Implement form
```

**JSON Output:**
```bash
tw --json list
```

#### `tw show ID`

Display detailed information about a single issue.

**Example:**
```bash
tw show PROJ-1-1a
```

**Output:**
```
PROJ-1-1a - Implement login form
Type: task
Status: done
Parent: PROJ-1-1

Create a responsive login form with username/password fields
and proper validation.
```

**JSON Output:**
```bash
tw --json show PROJ-1-1a
```

### Status Transitions

#### `tw start ID`

Start work on an issue (transitions NEW or STOPPED → IN_PROGRESS).

Adds a `[work-begin]` annotation to track when work started.

**Example:**
```bash
tw start PROJ-1-1a
# Output: Started work on PROJ-1-1a
```

**Valid Transitions:**
- `new` → `in_progress`
- `stopped` → `in_progress`

#### `tw done ID [--message TEXT]`

Mark an issue as complete (transitions IN_PROGRESS → DONE).

Adds a `[work-end]` annotation. Optionally add a comment describing the completion.

**Example:**
```bash
tw done PROJ-1-1a --message "Implemented with React Hook Form and Zod validation"
```

**Valid Transitions:**
- `in_progress` → `done`

#### `tw blocked ID --reason TEXT`

Mark an issue as blocked (transitions IN_PROGRESS → BLOCKED).

Records the blocking reason as a `[blocked]` annotation.

**Example:**
```bash
tw blocked PROJ-1-1a --reason "Waiting for API endpoint deployment"
```

**Valid Transitions:**
- `in_progress` → `blocked`

#### `tw unblock ID [--message TEXT]`

Unblock an issue (transitions BLOCKED → IN_PROGRESS).

Records the unblocking reason as an `[unblocked]` annotation.

**Example:**
```bash
tw unblock PROJ-1-1a --message "API endpoint is now live"
```

**Valid Transitions:**
- `blocked` → `in_progress`

#### `tw handoff ID --status TEXT --completed TEXT --remaining TEXT`

Hand off work with structured summary (transitions IN_PROGRESS → STOPPED).

This command is designed for AI agents to provide context before stopping work due to token limits, errors, or reaching a checkpoint.

**Options:**
- `--status, -s TEXT`: Current status summary (required)
- `--completed, -c TEXT`: What work has been completed (required)
- `--remaining, -r TEXT`: What work remains (required)

**Example:**
```bash
tw handoff PROJ-1-1a \
  --status "Reached context limit after implementing form validation" \
  --completed "- [x] Created LoginForm component\n- [x] Added Zod schema\n- [x] Implemented validation" \
  --remaining "- [ ] Connect to API\n- [ ] Add error handling\n- [ ] Write tests"
```

The handoff creates a `[handoff]` annotation with the structured summary, allowing the next agent to quickly understand what was accomplished and what needs to be done.

**Valid Transitions:**
- `in_progress` → `stopped`

## Issue Status Lifecycle

```
       new
        ↓
    ┌───────┐
    │ start │
    └───┬───┘
        ↓
   in_progress ←──────────┐
        │                 │
        ├─→ done          │
        │                 │
        ├─→ blocked ──→ unblock
        │
        └─→ stopped (handoff)
```

**Status Definitions:**
- **new**: Issue created but work not started
- **in_progress**: Actively being worked on
- **stopped**: Work paused, awaiting resumption (via handoff)
- **blocked**: Cannot proceed due to external dependency
- **done**: Work completed

## Annotations

Annotations are timestamped notes attached to issues. They support typed annotations for structured tracking:

**Annotation Types:**
- `[work-begin]`: Automatically added when starting work
- `[work-end]`: Automatically added when completing work
- `[blocked]`: Added with blocking reason
- `[unblocked]`: Added with unblocking reason
- `[handoff]`: Added with structured handoff summary
- `[lesson]`: Key learnings during work
- `[deviation]`: Deviations from plan or requirements
- `[commit]`: Git commit references
- `[comment]`: General comments

## Environment Variables

### `TW_DB_PATH`

Path to the SQLite database file for storing issues.

**Example:**
```bash
export TW_DB_PATH="$HOME/.tw/issues.db"
```

### `TW_PROJECT_PREFIX` (or `TW_PREFIX`)

The prefix used for generating issue IDs.

**Default:** `DEFAULT`

**Example:**
```bash
export TW_PROJECT_PREFIX="AUTH"
# Results in IDs like: AUTH-1, AUTH-1-1, AUTH-1-1a
```

## Global Options

### `--verbose, -v`

Enable debug logging to stderr.

```bash
tw --verbose list
```

### `--quiet, -q`

Suppress all non-error output.

```bash
tw --quiet start PROJ-1
```

### `--json`

Output results in JSON format for machine parsing.

```bash
tw --json list
tw --json show PROJ-1
```

### `--project-name TEXT`

Override the project name for a single command.

```bash
tw --project-name "otherproject" list
```

### `--project-prefix TEXT`

Override the project prefix for a single command.

```bash
tw --project-prefix "OTHER" new epic --title "Epic"
```

## Reference Extraction

The tool automatically extracts and tracks references to other issues in the body text.

**Example:**

```bash
tw new task --title "Refactor login" --parent PROJ-1-1 \
  --body "Refactor the login code from PROJ-1-1a and integrate with PROJ-2-3"
```

The issue will automatically have `tw_refs` containing `["PROJ-1-1a", "PROJ-2-3"]`, enabling dependency tracking and navigation.

## Development

### Running Tests

```bash
# Run all tests with coverage
pytest

# Run specific test file
pytest tests/test_service.py

# Run with verbose output
pytest -v

# Run without coverage report
pytest --no-cov
```

### Linting and Type Checking

```bash
# Format code with ruff
ruff format src/ tests/

# Lint code
ruff check src/ tests/

# Type check with mypy
mypy src/
```

### Code Style

This project follows these conventions:

- **Line length**: 100 characters
- **Python version**: 3.11+
- **Docstrings**: Google-style with type hints in signatures
- **Imports**: Sorted with ruff (isort rules)
- **Type hints**: Required for all function signatures

## Architecture

### Components

- **`tw.models`**: Core data models (Issue, Annotation, IssueType, IssueStatus)
- **`tw.backend`**: SQLite database integration layer
- **`tw.ids`**: ID parsing, generation, and sorting utilities
- **`tw.refs`**: Reference extraction from text
- **`tw.service`**: High-level business logic (IssueService)
- **`tw.cli`**: Click-based command-line interface

### Data Flow

```
CLI Command
    ↓
IssueService (business logic)
    ↓
SqliteBackend (database operations)
    ↓
SQLite Database
```

### Issue Hierarchy

```
Epic (PROJ-1)
├── Story (PROJ-1-1)
│   ├── Task (PROJ-1-1a)
│   ├── Task (PROJ-1-1b)
│   └── Task (PROJ-1-1c)
└── Story (PROJ-1-2)
    ├── Task (PROJ-1-2a)
    └── Task (PROJ-1-2b)
```

### Body Structure

Issue bodies support a special `---` separator for distinguishing repeatable context from session-specific details:

```
This text appears every time the issue is shown (repeatable).
It contains the core requirements and context.
---
This text is session-specific and might contain ephemeral notes,
links to logs, or other details that don't need to be repeated.
```

The repeatable portion (before `---`) is intended for agent consumption, while the full body is available when needed.

## License

[Specify license]

## Contributing

[Contribution guidelines]

## Support

[Support information]
