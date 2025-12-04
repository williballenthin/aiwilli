⏺ I've read the design document. This is a thoughtful approach to solving the context
  rot and work tracking problems for SWE agents. Let me address each of your questions:

  1. Critical Architectural Decisions

  Issue type storage: Taskwarrior has tags (+epic), UDAs (User Defined Attributes), and
  projects. I'd recommend a UDA called type with allowed values epic|story|task. This is
   cleaner than tags and queryable.

  Description storage: Taskwarrior's native description field is single-line. For
  multi-paragraph markdown content, we need to either: (a) store in annotations with a
  special prefix, (b) use a UDA for extended description, or (c) store descriptions in
  external files (e.g., .tw/descriptions/<uuid>.md) and reference them. Option (c) is
  cleanest for markdown editing with $EDITOR.

  Parent-child linking: You mention using depends for child→parent. This is backwards
  from Taskwarrior's semantics (depends means "blocked by"). Consider: use depends as
  parent→child (parent depends on children completing), or add a parent UDA. The former
  aligns with Taskwarrior's blocking logic.

  ID scheme: Taskwarrior uses volatile integer IDs and stable UUIDs. For agent
  communication, we need stable references. Options: use UUIDs, use short UUID prefixes,
   or maintain our own sequential IDs in a UDA.

  Project scoping: You mention TW_PROJECT_NAME. We need to decide if this maps to
  Taskwarrior's project: attribute directly or if we namespace it differently.

  2. Proposed Commands

  tw onboard              # Output usage guide for SWE agents (markdown)
  tw add <title>          # Add issue interactively or with flags
  tw add -t task "Fix the widget color"
  tw add -t story "Implement dark mode" --parent <id>

  tw list                 # List open issues in current project
  tw list --all           # Include done issues
  tw list --tree          # Show hierarchy
  tw list --ready         # Show actionable tasks (no blocking children)

  tw show <id>            # Show single issue details
  tw show <id> --context  # Show with ancestor/descendant context (for agents)
  tw show <id> --full     # Show everything including all comments

  tw edit <id>            # Open $EDITOR for description
  tw modify <id> [field=value...]  # Modify fields inline

  tw start <id>           # Mark in-progress
  tw done <id>            # Mark complete
  tw done <id> -m "Implemented per spec"  # With closing comment

  tw comment <id> "text"  # Add annotation/comment
  tw comment <id> --deviation "Changed X because Y"
  tw comment <id> --commit <sha>

  tw link <child> <parent>    # Establish parent-child relationship
  tw unlink <child>           # Remove parent link

  tw next                 # Show the next actionable task (lowest ID ready task)
  tw plan <epic-id>       # Output full plan view for an epic

  3. Questions to Explore the Design Space

  1. Conflict handling: What happens if a human modifies Taskwarrior directly via task
  command? Do we need to handle gracefully, warn, or just document "don't do that"?
  2. Multi-agent scenarios: You say single agent at a time, but what if you want to
  review one agent's filed issues before another starts? Any locking or "claim"
  mechanism?
  3. Repeatable text demarcation: You mentioned paragraph 2 as "repeatable" context. Is
  this rigid enough? Would explicit markers like <!-- repeatable --> be better?
  4. Context budget: When rendering --context view, should we have token/character
  limits? Oldest ancestor context might be stale or too verbose.
  5. VCS integration depth: Beyond storing commit refs in comments, should tw
  auto-detect uncommitted changes related to an in-progress issue? Or integrate with
  jj/git hooks?
  6. Completion criteria: Should tasks have explicit acceptance criteria that agents can
   self-verify? Or is that over-engineering?
  7. Priority/ordering: You mention ascending ID order. Should we also support explicit
  priority for "do this first regardless of ID"?

  4. Extension Ideas

  1. Context Snapshots: When an agent starts work on an issue, tw could snapshot the
  current context (related files, recent git diff, environment) into a .tw/snapshots/
  directory. If the agent is interrupted, a new agent can tw restore <id> to reconstruct
   the working state, reducing cold-start overhead.

  2. Agent Handoff Protocol: Define a structured tw handoff <id> command that an agent
  calls before context compaction. It writes a structured summary (what was done, what
  remains, blockers encountered) that the next agent session automatically reads via tw
  resume <id>.

  3. Templated Issue Types: Allow .tw/templates/bug.md, .tw/templates/refactor.md with
  predefined structure. tw add -t task --template bug pre-fills the description,
  ensuring agents capture consistent information (reproduction steps, expected behavior,
   etc.).

  4. Dependency Graph Visualization: tw graph outputs a Mermaid or Graphviz diagram of
  the issue hierarchy. Useful for humans to understand complex plans, and could be
  embedded in project documentation or rendered in terminal with ASCII art for quick
  orientation.

  5. Auto-Filing from Code Comments: tw scan parses the codebase for TODO(tw): or
  FIXME(tw): comments and auto-creates linked tasks. When the comment is removed (code
  changed), the corresponding issue could be auto-closed or flagged for review, keeping
  issues in sync with code reality.

  ---
  What aspects would you like to dig into further? I'm particularly curious about your
  thoughts on the description storage question and the parent-child linking semantics.
