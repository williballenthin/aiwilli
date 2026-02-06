---
name: brainstorming
description: Use when the user explicitly asks to brainstorm. Helps turn ideas into designs through collaborative dialogue.
---

# Brainstorming

Help turn ideas into designs and specs through collaborative dialogue.

## When to Invoke

Only invoke when the user explicitly asks to brainstorm. Examples:
- "Let's brainstorm this feature"
- "I want to brainstorm approaches for X"
- "Can we brainstorm how to solve Y?"

Do not auto-invoke for general implementation tasks or questions.

## Process

### 1. Understand the Context

Start by reviewing the current project:
- Check relevant files, docs, recent commits
- Understand what exists and what constraints apply

### 2. Ask Questions

Explore the idea through questions:
- Ask one question at a time
- Prefer multiple choice when options are clear
- Focus on: purpose, constraints, success criteria, edge cases
- Don't overwhelm - if a topic needs more exploration, ask follow-up questions
- Use your choices tool to prompt the user

### 3. Propose Approaches

Once you understand the problem:
- Propose 2-3 different approaches with trade-offs
- Lead with your recommendation and explain why
- Be direct about pros/cons

### 4. Present the Design

When ready to document:
- Break into sections of 200-300 words
- Check after each section if it looks right
- Cover: architecture, components, data flow, error handling
- Apply YAGNI - remove unnecessary features

If the user asks to handoff, jump ahead to the next phase, such as planning or implementation.

### 5. Update spec.md

If the project has an associated spec.md, consider how the brainstorming session clarified the behavioral specification.
Don't include implementation details, just how the project is intended to be used, function, display, etc.
- be concise and direct. show examples. technical is ok.
- describe intended behavior, but not undefined behavior.
- no slop. no bold. no emojis. simple text like my style.

## Principles

- **One question at a time** - don't overwhelm
- **YAGNI** - remove unnecessary features from designs
- **Explore alternatives** - always propose 2-3 approaches
- **Incremental validation** - present in sections, validate each
- **Be flexible** - go back and clarify when needed
