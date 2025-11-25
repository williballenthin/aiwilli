---
name: codex-review
description: Request an external review from Codex (OpenAI) to get a second perspective on designs, implementations, diffs, or architecture decisions
---

# Codex Review

Use this skill when you need a second perspective on work in progress. Codex excels at identifying gaps in reasoning, missing requirements, architectural concerns, and flawed assumptions - especially early in the planning process when issues are cheapest to fix.

## When to Use

Invoke this skill when the user wants an external perspective, especially during early phases:
- Brainstorming sessions - validating ideas and approaches
- Requirements gathering - checking for gaps or contradictions
- Design documents - reviewing architecture and technical decisions
- Implementation plans - validating approach before writing code
- Occasionally: reviewing code or diffs when explicitly requested

## How to Invoke Codex

Codex runs in non-interactive mode via `codex exec`. Pass all content directly via stdin.

**Command template:**
```bash
printf "%s" "$CONTENT_TO_REVIEW" | codex exec \
  -m "gpt-5.1-codex-max" \
  -c 'model_reasoning_effort="high"' \
  -s read-only \
  -
```

The `-` at the end tells Codex to read the prompt from stdin. Use `printf "%s"` instead of `echo` to safely handle content with backslashes or leading dashes.

## Preparing the Content

Before invoking Codex, gather all relevant context into a single prompt. Codex has no access to the filesystem or any context beyond what you provide.

**Important:** Strip sensitive data (API keys, tokens, credentials, secrets) from content before sending to Codex. If the context is unclear or you need specific focus areas, prompt the user for guidance.

**For brainstorming or ideas:**
```
## Review Request: Idea Validation

Please review the following ideas/approach for gaps, risks, and flawed assumptions.

### Proposal:
<the idea, approach, or brainstorm output>

### Context:
<problem being solved, constraints, goals>
```

**For requirements:**
```
## Review Request: Requirements

Please review these requirements for completeness, contradictions, and missing edge cases.

### Requirements:
<the requirements>

### Context:
<what system/feature these are for>
```

**For design documents:**
```
## Review Request: Design

Please review the following design for gaps, risks, and potential issues.

### Design:
<the design document or architecture>

### Context:
<background, constraints, goals>
```

**For code or diffs (when explicitly requested):**

Fetch the content using the project's VCS (git, jj, etc.) with color codes stripped. Frame the request appropriately:
```
## Review Request: Implementation

Please review the following for correctness, edge cases, and potential issues.

### Content:
<code or diff>

### Context:
<what this does, why it was changed>
```

## The Review Prompt

Always append these instructions to ensure structured output:

```
---

## Output Format

Provide your review in the following sections only:

### Blocking Issues
Issues that MUST be addressed before proceeding. These are bugs, security vulnerabilities, logic errors, or design flaws that would cause problems.

### Non-blocking Issues
Suggestions for improvement that are not critical. Style concerns, minor optimizations, or alternative approaches worth considering.

### Outstanding Questions
Questions that need clarification from the author. Ambiguities in requirements, unclear design decisions, or missing context.

### Further Ideas
Optional enhancements or future considerations. Ideas that could improve the work but are out of scope for now.

If a section has no items, write "None identified."
```

## Full Example

```bash
# Build the prompt with content and output format instructions
PROMPT=$(cat <<'REVIEW_EOF'
## Review Request: Design

Please review the following design for gaps, risks, and potential issues.

### Design:
We're building a caching layer for our API. The plan is:
1. Use Redis for distributed caching
2. Cache all GET responses for 5 minutes
3. Invalidate on any write operation to related resources
4. Fall back to database on cache miss

### Context:
- High-traffic API (~10k requests/minute)
- Eventually consistent is acceptable
- Must not serve stale data after writes

### Additional Focus:
Pay attention to cache invalidation edge cases.

---

## Output Format

Provide your review in the following sections only:

### Blocking Issues
Issues that MUST be addressed before proceeding. These are bugs, security vulnerabilities, logic errors, or design flaws that would cause problems.

### Non-blocking Issues
Suggestions for improvement that are not critical. Style concerns, minor optimizations, or alternative approaches worth considering.

### Outstanding Questions
Questions that need clarification from the author. Ambiguities in requirements, unclear design decisions, or missing context.

### Further Ideas
Optional enhancements or future considerations. Ideas that could improve the work but are out of scope for now.

If a section has no items, write "None identified."
REVIEW_EOF
)

# Invoke Codex
printf "%s" "$PROMPT" | codex exec \
  -m "gpt-5.1-codex-max" \
  -c 'model_reasoning_effort="high"' \
  -s read-only \
  -
```

## After the Review

1. Display the full review report to the user
2. Prompt the user to:
   - Answer any outstanding questions
   - Address blocking issues (these should be resolved)
   - Comment on non-blocking issues and further ideas (accept, reject, or defer)
3. If the user wants to address issues, help them implement the fixes
4. Consider re-running the review after significant changes
