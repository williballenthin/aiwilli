# Design: `tw claude` Command

## Overview

A new CLI command that launches Claude with an issue's brief as the initial prompt. Supports both interactive fuzzy selection and direct issue ID specification.

## Usage

```bash
tw claude           # Fuzzy select from actionable issues, then launch claude
tw claude TW-87     # Launch claude directly with TW-87's brief
```

## Behavior

- When no ID provided: show questionary autocomplete with actionable issues (status: new, active, blocked)
- When ID provided: skip selection, use that issue directly
- Executes: `claude "<brief-content>"`

## Implementation

**Location:** `src/tw/cli.py`

**Code structure:**
```python
@cli.command()
@click.argument("tw_id", required=False, default=None)
@click.pass_context
def claude(ctx: click.Context, tw_id: str | None) -> None:
    service = get_service(ctx)

    if tw_id is None:
        # Fuzzy select from actionable issues
        issues = service.list_issues()
        actionable = [i for i in issues if i.status in ("new", "active", "blocked")]
        # Show questionary autocomplete
        tw_id = selected

    # Get brief and launch claude
    brief_output = render_brief(issue, ...)
    subprocess.run(["claude", brief_output])
```

**Key points:**
- Reuses existing `render_brief()` function
- Follows same pattern as `tw edit` for fuzzy selection
- Uses `subprocess.run()` to hand off to claude CLI
