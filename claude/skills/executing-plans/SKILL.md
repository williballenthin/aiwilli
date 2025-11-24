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

### 7. Report Final Status with Deviations

**CRITICAL:** After completing all tasks and final review, you MUST provide a clear status report highlighting:

**Required in final status:**
- **Deviations from plan:** Any tasks that were implemented differently than specified
- **Things that went wrong:** Failures, errors, or unexpected issues encountered
- **Things skipped:** Any plan items not completed and why
- **Special handling:** Workarounds, manual interventions, or non-standard approaches used
- **Assumptions made:** Decisions made where plan was unclear
- **Impact assessment:** How deviations affect the overall implementation

**Format:**
```
## Execution Complete

### Summary
[Brief overview of what was accomplished]

### Deviations and Issues
[REQUIRED - if none, explicitly state "No deviations from plan"]

- **Task N:** [What went wrong/differently and why]
- **Skipped:** [What was skipped and justification]
- **Special handling:** [Any workarounds or manual fixes]

### Final Review Results
[Code reviewer assessment]

### Status
[Ready for merge / Needs attention / Blocked]
```

**If no deviations:** Explicitly state "No deviations from the plan. All tasks completed as specified."

**Never skip this step.** Transparency about issues builds trust and helps users understand what happened.


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

[Report final status with deviations]

## Execution Complete

### Summary
Implemented hook installation and recovery modes. All 13 tests passing.

### Deviations and Issues
- **Task 2:** Added progress reporting (not in original plan) - reviewer identified as missing during code review, fixed in ghi789
- **Special handling:** Had to refactor error handling pattern to support both verify and repair modes consistently

### Final Review Results
Code reviewer: All requirements met, good test coverage, consistent patterns. Ready to merge.

### Status
Ready for merge
```

## Advantages

**vs. Manual execution:**
- Subagents follow TDD naturally
- Fresh context per task (no confusion)
- Parallel-safe (subagents don't interfere)
- Linting enforced before each code review (consistent quality)

**Cost:**
- More subagent invocations
- But catches issues early (cheaper than debugging later)

## Red Flags

**Never:**
- Skip code review between tasks
- Proceed with unfixed Critical issues
- Dispatch multiple implementation subagents in parallel (conflicts)
- Implement without reading plan task
- **Skip final status report with deviations** - ALWAYS report what went differently

**If subagent fails task:**
- Dispatch fix subagent with specific instructions
- Don't try to fix manually (context pollution)
- Document the failure in final status report

## Integration

**Required workflow skills:**
- **writing-plans** - REQUIRED: Creates the plan that this skill executes
- **requesting-code-review** - REQUIRED: Review after each task (see Step 3)

**Required subagents:**
- **wb:task-implementer** - Executes individual tasks following TDD (see agents/task-implementer.md)
- **wb:code-reviewer** - Reviews completed work (see agents/code-reviewer.md)

**Embedded skills (subagent uses):**
- **test-driven-development** - wb:task-implementer follows TDD for each task
