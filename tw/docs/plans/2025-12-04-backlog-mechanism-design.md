# Backlog Mechanism Design

Issue: TW-8

## Overview

A lightweight mechanism for humans and SWE agents to quickly capture discovered work (bugs, ideas) without immediately deciding the epic/story/task structure. Backlog items sit in a holding area until groomed into proper entries.

## New Backlog Types

Two new issue types: `bug` and `idea`

These are separate from the epic/story/task hierarchy - they represent ungroomed work waiting to be prioritized and structured.

**Properties:**
- **tw_type**: `bug` or `idea` (alongside existing `epic`, `story`, `task`)
- **tw_id**: Top-level IDs (e.g., `TW-12`, `TW-13`) - same namespace as epics
- **tw_status**: Only `new` or `done` (simplified lifecycle)
- **tw_parent**: Always empty (orphans only)
- **description**: Title (first line)
- **tw_body**: Full markdown content with `---` separator for repeatable/non-repeatable

**Source context:** Captured in body text. Any referenced task IDs (e.g., "Discovered while working on TW-5-2a") are automatically extracted to `tw_refs`.

## Commands

### Creating backlog items

```
tw new bug [--title "<title>"] [--body "<body or - for stdin>"]
tw new idea [--title "<title>"] [--body "<body or - for stdin>"]
```

Same pattern as existing `tw new epic|story|task`, but no `--parent` option. If `--title` not provided, opens `$EDITOR` with template.

### Grooming backlog

```
tw groom
```

No arguments. Opens `$EDITOR` with all `new` bugs/ideas pre-populated. On save:
- Items transformed into epic/story/task/bug/idea → created, original resolved
- Items removed → original resolved (dismissed)
- Items unchanged → original stays `new`

### Resolving without grooming

```
tw done <id>
```

Works on bugs/ideas too - marks as `done` without creating new entries (for items you decide not to pursue).

## Multi-line Capture/Groom Format

The format for `tw capture` and `tw groom` supports multi-line bodies:

```
- bug: login broken on empty password
    The login form crashes when password field is empty.
    Discovered while working on TW-5-2a.
    ---
    Reproduction: open login, leave password blank, click submit.
    Stack trace shows null pointer in validator.
- idea: add password strength meter
    Would improve UX by showing password strength.
- epic: authentication overhaul
  - story: fix login bugs
    - task: handle empty fields
        Validate all form fields before submission.
```

**Parsing rules:**
- `- type: title` starts a new item (indentation determines hierarchy for epic/story/task)
- Indented lines below are body content
- Leading whitespace is trimmed to normalize the body
- Body uses existing `---` separator for repeatable/non-repeatable
- Lines starting with `#` are comments (ignored)
- Empty lines within body are preserved

**For `tw groom` output:** Each backlog item is rendered in this format, with its current ID shown in a comment for reference (e.g., `# TW-12`).

## Tree Display

`tw tree` shows two sections:

```
epic: Authentication System (TW-1) [in_progress]
  story: Login Flow (TW-1-1) [done]
    task: implement form (TW-1-1a) [done]
    task: add validation (TW-1-1b) [done]
  story: Password Reset (TW-1-2) [new]
    task: design email template (TW-1-2a) [new]

───────────────── Backlog ─────────────────

bug: login broken on empty password (TW-12) [new]
idea: add password strength meter (TW-13) [new]
```

**Display rules:**
- Top section: epic/story/task hierarchy (existing behavior)
- Separator line
- Bottom section: all bugs/ideas (flat list, no hierarchy)
- Completed backlog items hidden (same as completed epics with all descendants complete)
- Status shown in brackets, muted color for done items

## Implementation Details

**UDA changes:**
- `tw_type`: Add `bug` and `idea` to allowed values (existing: `epic`, `story`, `task`)
- No new UDAs needed

**Validation rules:**
- Bugs/ideas cannot have parents (`--parent` option rejected)
- Bugs/ideas cannot have children (error if trying to set parent to a bug/idea)
- Bugs/ideas only support `new` → `done` status transitions
- `tw start`, `tw stop`, `tw handoff`, `tw blocked`, `tw unblocked` reject bugs/ideas with helpful error

**ID generation:**
- Bugs/ideas get next available top-level ID (same pool as epics)
- No reserved slot logic needed - they're just top-level items

**tw_refs extraction:**
- Runs on body write for bugs/ideas (same as other types)
- Backlinks queryable via existing filter mechanism

## Groom Workflow

**When `tw groom` is invoked:**

1. Query all bugs/ideas with `tw_status=new`
2. Generate editor content with each item in the multi-line format:
   ```
   # TW-12 (bug)
   - bug: login broken on empty password
       The login form crashes when password field is empty.
       Discovered while working on TW-5-2a.

   # TW-13 (idea)
   - idea: add password strength meter
       Would improve UX by showing password strength.
   ```
3. Open `$EDITOR`
4. On save, parse the document and compare to original:
   - **Item transformed** (e.g., `# TW-12` line followed by `- task: ...`): Create new entry, mark TW-12 as `done`
   - **Item removed** (no `# TW-12` line or empty after it): Mark TW-12 as `done`
   - **Item unchanged**: Leave TW-12 as `new`
   - **New items** (no `# TW-XX` comment above): Create as specified

5. Print summary of actions taken

## Files to Modify

- `cli.py` - new commands
- `service.py` - groom logic, validation for backlog types
- `render.py` - tree backlog section, groom format generation/parsing
- `templates/` - tree template update
- `tests/` - comprehensive tests for multi-line parsing
