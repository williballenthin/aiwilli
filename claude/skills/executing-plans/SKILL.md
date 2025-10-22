---
name: executing-plans
description: Use when executing implementation plans with independent tasks in the current session - dispatches fresh subagent for each task with code review between tasks, enabling fast iteration with quality gates
---

# Executing Plans

Execute plan by dispatching fresh subagent per task, with code review after each.

**Core principle:** Fresh subagent per task + review between tasks = high quality, fast iteration

## Overview

**When to use:**
- Staying in this session
- Tasks are mostly independent
- Want continuous progress with quality gates

**When NOT to use:**
- Tasks are tightly coupled (manual execution better)
- Plan needs revision (brainstorm first)

## The Process

### 1. Load Plan

Read plan file, create TodoWrite with all tasks.

### 2. Execute Task with Subagent

For each task:

**Dispatch wb:task-implementer subagent:**
```
Task tool with wb:task-implementer:
  description: "Implement Task N: [task name]"
  prompt: |
    You are implementing Task N from [plan-file-path].

    Read the task specification carefully and implement it following TDD.

    Working directory: [path]

    Report your results when complete.
```

**Subagent reports back** with structured summary of work.

### 3. Review Subagent's Work

Use the requesting-code-review skill to review the work.

**Code reviewer returns:** Strengths, Issues (Critical/Important/Minor), Assessment

### 4. Apply Review Feedback

**If critical or important issues found:**

Dispatch wb:task-implementer again with fix instructions:

```
Task tool with wb:task-implementer:
  description: "Fix issues from Task N code review"
  prompt: |
    You previously implemented Task N from [plan-file-path].

    The code review found these issues that need fixing:
    [list issues with file:line references]

    Fix these issues and report your results.

    Working directory: [path]
```

### 5. Mark Complete, Next Task

- Mark task as completed in TodoWrite
- Move to next task
- Repeat steps 2-5

### 6. Final Review

After all tasks complete, dispatch final code-reviewer:
- Reviews entire implementation
- Checks all plan requirements met
- Validates overall architecture


## Example Workflow

```
You: I'm using executing-plans to execute this plan.

[Load plan, create TodoWrite]

Task 1: Hook installation script

[Dispatch wb:task-implementer]
Subagent: Implemented install-hook with tests, 5/5 passing, committed as abc123

[Get commit SHAs (see @working-with-git or @working-with-jj), dispatch wb:code-reviewer]
Reviewer: Strengths: Good test coverage. Issues: None. Ready.

[Mark Task 1 complete]

Task 2: Recovery modes

[Dispatch wb:task-implementer]
Subagent: Added verify/repair, 8/8 tests passing, committed as def456

[Dispatch wb:code-reviewer]
Reviewer: Strengths: Solid. Issues (Important): Missing progress reporting

[Dispatch wb:task-implementer with fix instructions]
Fix subagent: Added progress every 100 conversations, committed as ghi789

[Verify fix, mark Task 2 complete]

...

[After all tasks]
[Dispatch wb:code-reviewer for final review]
Final reviewer: All requirements met, ready to merge

Done!
```

## Advantages

**vs. Manual execution:**
- Subagents follow TDD naturally
- Fresh context per task (no confusion)
- Parallel-safe (subagents don't interfere)

**Cost:**
- More subagent invocations
- But catches issues early (cheaper than debugging later)

## Red Flags

**Never:**
- Skip code review between tasks
- Proceed with unfixed Critical issues
- Dispatch multiple implementation subagents in parallel (conflicts)
- Implement without reading plan task

**If subagent fails task:**
- Dispatch fix subagent with specific instructions
- Don't try to fix manually (context pollution)

## Integration

**Required workflow skills:**
- **writing-plans** - REQUIRED: Creates the plan that this skill executes
- **requesting-code-review** - REQUIRED: Review after each task (see Step 3)

**Required subagents:**
- **wb:task-implementer** - Executes individual tasks following TDD (see agents/task-implementer.md)
- **wb:code-reviewer** - Reviews completed work (see agents/code-reviewer.md)

**Embedded skills (subagent uses):**
- **test-driven-development** - wb:task-implementer follows TDD for each task
