# AGENTS.md

## Documentation contract

When working in this repository, keep these documents current:

- `memory/docs/spec.md` — **user-facing behavior**
- `memory/docs/design.md` — **implementation details**

Record decisions in `spec.md` and/or `design.md`.

- Put behavior/interface decisions in **spec**.
- Put architecture/class/method/logic decisions in **design**.
- If a change affects both behavior and implementation, update both.
- Keep both docs in sync with current thinking **and** the actual code.

## Update rules

1. If user-visible behavior changes, update `spec.md` in the same change.
2. If implementation structure changes (modules, classes, config shape, data flow), update `design.md` in the same change.
3. Keep examples (paths, model names, CLI commands, config snippets) aligned with reality.
4. Keep open questions explicit in the docs until decided.

## Work loop rules

After any meaningful chunk of work, always:

1. Run lint.
2. Run tests.
3. Commit the changes.
