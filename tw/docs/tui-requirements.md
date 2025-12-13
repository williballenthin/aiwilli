# TW TUI Requirements Document

This document describes the requirements for the TW issue tracker's Terminal User Interface (TUI). It is intended to serve as a specification for reimplementing the TUI with a different UI toolkit.

## Overview

The TUI provides an interactive terminal interface for managing issues in the TW issue tracker. It displays a hierarchical issue tree alongside issue details, supporting navigation, status changes, issue creation, and editing.

## Layout

The interface uses a vertical split layout with three regions:

```
┌─────────────────────────────────────────────────────────────┐
│                     TREE PANE (60%)                         │
│  Scrollable list showing issue hierarchy                    │
├─────────────────────────────────────────────────────────────┤
│                   DETAIL PANE (40%)                         │
│  Markdown body + related issues for selected item           │
├─────────────────────────────────────────────────────────────┤
│  FOOTER - Keybinding hints                                  │
└─────────────────────────────────────────────────────────────┘
```

### Tree Pane (60% height)

**Purpose:** Display all issues in a navigable tree structure.

**Visual properties:**
- Solid border (primary color)
- Stable scrollbar gutter
- Full width content area

**Content structure:**
- Issues displayed as a flat list with indentation representing hierarchy depth
- 2 spaces per level of indentation
- Backlog items (bugs/ideas) displayed at depth 0 after the hierarchy

**Line format:**
```
[indent][type]: [title] ([tw_id], [status])
```

Example:
```
epic: Auth System (TW-1)
  story: Login Flow (TW-1-1, in_progress)
    task: Add validation (TW-1-1a)
  story: Logout Flow (TW-1-2, done)
bug: Memory leak (TW-10)
idea: Dark mode (TW-11)
```

**Selection:**
- Single item selection (highlighted with reverse video)
- Preserved across data refresh when possible

**Status styling:**
| Status | Styling |
|--------|---------|
| done | Entire line dimmed (gray) |
| in_progress | Status portion in yellow |
| blocked, stopped | Status portion in red |
| new (default) | Normal text, status not shown |

**Type styling:**
- Type label always dimmed

### Detail Pane (40% height)

**Purpose:** Display full details and context for the selected issue.

**Visual properties:**
- Solid border (accent color)
- Vertical scroll on overflow
- 1 unit horizontal padding

**Content sections:**

1. **Body (Markdown rendered):**
   - Header: `# [tw_id]: [title]`
   - Handoff notice (if status is stopped and handoff annotation exists): `> **HANDOFF:** [message]`
   - Properties line: `*[type] | [status] | parent: [parent_id] | refs: [ref_ids]*`
   - Body text (if present)
   - Annotations section (if present, excludes work-begin/work-end types)

2. **Links (Rich text):**
   - **Ancestors:** Parent chain leading to root (displayed in reverse order, root last)
   - **Siblings:** Issues with the same parent
   - **Descendants:** Child issues (recursive)
   - **Referenced Issues:** Issues mentioned in this issue's refs
   - **Issues Referencing This:** Issues that reference this issue

### Footer

Auto-generated keybinding hints showing available actions.

## Data Model

### Issue

| Field | Type | Description |
|-------|------|-------------|
| uuid | string | TaskWarrior UUID |
| tw_id | string | Human-readable ID (e.g., "TW-1-1a") |
| tw_type | IssueType | epic, story, task, bug, idea |
| title | string | Issue title |
| tw_status | IssueStatus | new, in_progress, stopped, blocked, done |
| project | string | Project identifier |
| tw_parent | string? | Parent issue's tw_id |
| tw_body | string? | Markdown body content |
| tw_refs | string[]? | Referenced issue IDs |
| annotations | Annotation[]? | Issue annotations |

### IssueType (enum)
- `epic` - Top-level work item
- `story` - Child of epic
- `task` - Child of story or task
- `bug` - Backlog item (no parent)
- `idea` - Backlog item (no parent)

### IssueStatus (enum)
- `new` - Not started
- `in_progress` - Currently being worked
- `stopped` - Paused with handoff
- `blocked` - Blocked on something
- `done` - Completed

### Annotation

| Field | Type | Description |
|-------|------|-------------|
| type | AnnotationType | Type of annotation |
| timestamp | datetime | When annotation was created |
| message | string | Annotation content |

### AnnotationType (enum)
- `work-begin` - Started working (hidden in detail view)
- `work-end` - Stopped working (hidden in detail view)
- `lesson` - Lesson learned
- `deviation` - Plan deviation
- `commit` - Related commit
- `handoff` - Handoff note (shown prominently when stopped)
- `blocked` - Blocked note
- `unblocked` - Unblocked note
- `comment` - General comment

## Keybindings

| Key | Action | Description |
|-----|--------|-------------|
| `q` | quit | Exit the application |
| `j` / `↓` | tree_move_down | Move selection down |
| `k` / `↑` | tree_move_up | Move selection up |
| `s` | start | Mark selected issue as in_progress |
| `d` | done | Mark selected issue as done |
| `e` | edit | Edit selected issue in external editor |
| `n` | new_child | Create child issue under selected |
| `N` | new_epic | Create new top-level epic |
| `b` | new_bug | Create new bug in backlog |
| `i` | new_idea | Create new idea in backlog |
| `p` | promote_issue | Promote backlog item to hierarchy |
| `r` | reparent | Move issue to a different parent |
| `c` | comment | Add comment to selected issue |
| `g` | groom | Groom backlog via external editor |
| `Escape` | close_dialogs | Close any open dialogs |

**Footer visibility:**
- `j`, `k`, `↓`, `↑`, `Escape` are hidden from footer
- All other keybindings shown

## Mouse Support

- Clicking on a tree row selects that issue
- Click coordinates converted to row index accounting for scroll offset

## Actions

### Status Changes

**Start (s):**
- Marks selected issue as `in_progress`
- Refreshes tree

**Done (d):**
- Marks selected issue as `done`
- Refreshes tree

### Editing

**Edit (e):**
1. Suspend TUI
2. Generate edit template with current title and body
3. Open in external editor (`$EDITOR` or `vi`)
4. Parse edited content back
5. Update issue with new title/body
6. Resume TUI and refresh

### Issue Creation

**New Child (n):**
- Requires selection
- Shows input dialog for title
- Infers child type from parent:
  - EPIC → STORY
  - STORY → TASK
  - TASK → TASK
- Creates issue with parent relationship

**New Epic (N):**
- Shows input dialog for title
- Creates top-level EPIC issue

**New Bug (b):**
- Shows input dialog for title
- Creates BUG in backlog (no parent)

**New Idea (i):**
- Shows input dialog for title
- Creates IDEA in backlog (no parent)

### Backlog Operations

**Promote (p):**
1. Verify selected issue is backlog type (bug/idea)
2. Show picker dialog with available epics/stories
3. User selects parent
4. Create new issue (STORY if parent is EPIC, else TASK)
5. Copy title and body from original
6. Mark original backlog item as done

**Re-parent (r):**
1. Verify selected issue is not a backlog type
2. Show picker dialog with available parents (epics/stories/tasks) plus "(none)" option
3. User selects new parent
4. Create new issue under the new parent with appropriate type
5. Copy all metadata (title, body, annotations, status)
6. Recursively move any children
7. Delete original issue

**Groom (g):**
1. Suspend TUI
2. Run `tw groom` command
3. Resume TUI and refresh

### Comments

**Comment (c):**
- Shows input dialog
- Adds COMMENT annotation to selected issue

## Dialogs

### Input Dialog

**Purpose:** Single-line text input for titles and comments.

**Appearance:**
- Docked at bottom of screen
- Full width
- No border on input field
- Panel background

**Behavior:**
- Auto-focuses input on mount
- Enter submits and closes
- Escape closes without action

### Picker Dialog

**Purpose:** Select from a filterable list of options.

**Appearance:**
- Docked at bottom
- Full width, 20 lines height
- Heavy border (primary color)
- Panel background
- Horizontal padding

**Components:**
1. Bold title at top (centered)
2. Filter input field
3. Option list (remaining height)

**Behavior:**
- Auto-focuses filter input on mount
- Filters options as user types (matches ID or display text)
- Click/Enter on option selects and invokes callback
- Escape closes without action

## Auto-Refresh

**Trigger:** File changes in TaskWarrior data directory.

**Behavior:**
- Watches `.data` files in TaskWarrior data directory
- Debounces with 100ms timer
- Only refreshes if user has been idle > 2 seconds
- Polls every 500ms
- Preserves selection on refresh

**Idle tracking:**
- Timestamp updated on any keybind action
- Prevents refresh during active user interaction

## Initialization

1. Create TaskWarrior backend
2. Create IssueService with project and prefix from config
3. Initialize file watch event (threading.Event)
4. Mount tree pane with service
5. Mount detail pane with service
6. Mount footer
7. Load initial tree data
8. Update detail pane with first selected item
9. Start file watcher (Watchdog observer)
10. Start refresh timer (500ms interval)

## Cleanup

On quit:
1. Stop refresh timer
2. Cancel pending file watch timers
3. Stop Watchdog observer
4. Join observer thread (1s timeout)
5. Exit application

## Error Handling

- Service initialization failures logged but app continues with error display
- All action handlers wrapped in try-except
- Errors logged via Python logging
- Status messages shown via logging (no modal error dialogs)

## External Dependencies

**Required services:**
- IssueService - CRUD operations, issue tree, issue context
- TaskWarriorBackend - Backend storage
- Configuration - project name, ID prefix

**External commands:**
- `$EDITOR` or `vi` - Issue editing
- `tw groom` - Backlog grooming
