• Architectural decisions to lock down

  - Issue typing: encode epic/story/task via tags vs UDAs; how to enforce allowed values;
    whether to store in description header for human readability.
  - Description structure: how to mark the “repeatable” context slice (second paragraph
    convention vs explicit marker) and how to parse/write it safely without mangling user-
    authored Markdown.
  - Link model: strictly parent→child via depends only or allow cross-links; rules
    preventing cycles; how to infer/validate hierarchy depth (task→story→epic) and ordering
    by ID.
  - Status and transitions: mapping open/in-progress/done to Taskwarrior statuses/UDAs;
    allow “blocked”/“waiting”; what side effects to enforce (e.g., mark parent done when all
    children done?).
  - Project scoping: how to resolve TW_PROJECT_NAME/PROJECT_NAME/default; whether to auto-
    tag tasks per repo path; safe-guards against cross-project contamination.
  - Rendering and context assembly: which ancestors/descendants to pull, how deep, ordering,
    truncation; include annotations? type labels? repeatable-only vs full description views
    for agents.
  - Editing UX: $EDITOR flow, conflict handling if task mutated concurrently, dry-run/
    preview.
  - Persistence/layout: storing CLI configs/templates; reproducible command outputs for
    agents (stable JSON schema).
  - Validation: guardrails to prevent adding stories under tasks or tasks under epics;
    ensuring parent exists on add; optional lint command.

  Proposed tw commands (agent/human friendly)

  - tw onboard: print concise help/usage and best practices.
  - tw add <type> "<title>" [--parent <id>] [--repeatable <file|->] [--body <file|->]:
    create epic/story/task, auto-assign project, optionally attach parent via depends,
    capture repeatable+full description.
  - tw edit <id>: open $EDITOR on description with structured sections; re-parse and update.
  - tw annotate <id> "comment": add Taskwarrior annotation for deviations, commits, lessons.
  - tw status <id> <open|in_progress|done>: update status with validation (e.g., cannot
    start if parent not open unless --force).
  - tw link child parent: add depends edge (enforce hierarchy rules); tw unlink child parent
    to remove.
  - tw show <id> [--mode agent|human] [--json]: render issue with type, status, repeatable
    block, full body, ancestors, children (ordered by ID), annotations; JSON for agents.
  - tw ls [--type epic|story|task] [--status ...] [--project ...] [--parent <id>] [--ready]
    [--json]: list/filter tasks; --ready = open with parents done.
  - tw tree <id>: show hierarchy around an issue (ancestors + descendants).
  - tw plan <id>: show ordered execution queue of descendant tasks by ID with statuses.
  - tw validate: lint hierarchy/status consistency, missing parents, cycles.
  - tw template list/apply: optional helpers to scaffold common epic/story/task
    descriptions.

  Design questions to clarify

  - Should issue type live as a Taskwarrior UDA (string enum) or tags? Do we want to surface
    it in the description header too?
  - How should the repeatable section be delimited—second paragraph convention, fenced
    marker (e.g., <!-- repeatable -->), or front-matter field? Should edits preserve
    arbitrary Markdown exactly?
  - Exact status mapping: use Taskwarrior pending/waiting/completed or custom UDA? Allow
    blocked or review states?
  - Enforcement rules: must every story have an epic parent? must every task have a story
    parent? allow epics without parents? allow cross-link references beyond depends?
  - When assembling agent context, do we include annotations and non-repeatable text from
    ancestors/descendants, or only repeatable slices? Depth limits?
  - Should parents auto-complete when all children done, or stay manual? Should starting a
    child auto-mark parent in-progress?
  - Do you want tw to auto-add a repo tag or cwd hint for later filtering? Should it prevent
    writing to a different project than resolved env var?

Five extension ideas (three sentences each)

  - Agent-friendly context export: tw context <id> --json returns a compact graph slice with
    repeatable text, key annotations, and execution order, minimizing tokens; agents can
    ingest this directly; optionally include “commands to run next”.
  - Templates with prompts: allow per-type templates that include guiding questions for
    agents (e.g., acceptance criteria, risks); tw add --template refactor prepopulates
    sections; helps produce consistent, high-quality descriptions.
  - Session journaling: tw session start <id> logs a timeboxed session, captures commands
    run (opt-in), and auto-annotates the issue on stop; creates a lightweight worklog; aids
    handoff between agents/humans.
  - Safety rails: tw guard can block status changes when parent blocked or missing
    repeatable text; suggests fixes; prevents malformed graphs before agents proceed.
  - VCS hooks: tw commit-link <id> <commit> annotates tasks with commit SHA; optional pre-
    commit hook reminds you to reference an in-progress task; improves traceability and
    later context for agents.
  
    
