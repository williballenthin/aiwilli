# Introduction

Okay, I'd like you to help me design a new application, a command line application. used to track issues and pending work in local software development scenarios That will be used by both a combination of me, the human software engineer, as well as my LLM-based AI software engineering agents like Claude Code and OpenAI's Codex The inspiration for this work is a project called Beads. And I'll include a link to that and it's Read Me below. The primary problem that I'm trying to solve are as follows. One, a place that I can very easily Record tasks, ideas, bugs, things to do and cue them up for subsequent implementation by the software engineering agent I do not use multiple workspaces to separate my agents that are writing code for me. I don't have many different branches going in parallel. For my projects, I typically use a single branch and a single directory. And I typically have one agent working at a time on that code. I don't plan on changing this. But what I have noticed is that while an agent is doing work for me, that might take a few minutes to tens of minutes, then I turn my attention elsewhere. Maybe I test the app or I review the code and I identify some other things that also need to be to be done. I need a place that's very easy to capture these notes, these things that I want to do. and be able to refer to them in subsequent delegation to these software engineering agents. The other primary problem that I'm trying to address is the fact that these software engineering agents have a limited context window. And for larger projects and tasks, they can't do it in a single shot within a single context window. After they approach 50% or 75% or 90% of their context window, they start encountering context rot. where they're no longer able to remember details carefully from earlier in the session. And when they hit their context limit, this the harness the framework may compact the existing session and key details are lost So what this means is that no real thread of work can extend beyond a single context window. without specialized handling. Now I've had good success by using subagents, particularly within clawed code. where there's a master, leader, coordinator agent that is able to spawn sub-agents to do smaller tasks. Subagent uses up portions of its context window to complete a task, returns control to the orchestrator who uses a comparably small number of tokens to invoke the next subagent to do the the next task. This is a great way to extend. kind of this lifetime of a project's implementation with a software engineering agent and to combat context rot. But it suffers from issues when the supervising agent either goes off the rails or is interrupted or I have to reboot my system. We lose track of where we were, how that agent was thinking, and how to restore the state of the system. So what I'd like to be able to do with this new tool that we're going to design together It should allow us to describe the tasks that need to be done in a hierarchical way, a lot like Jira. or another issue tracker. It'll do this in a very lightweight way. But we'll want to be able to describe describe phases of works. Or Well, in Jira terminology, epics and stories and tasks. Specifically, we'll be able to describe these different items. They may represent small localized changes or the coordination of multiple localized changes or a long-running effort that describes many stories. Importantly, there are links among these items. We don't want to over-engineer the different types of links and things, but what we do want is to be able to enumerate the links forward and backwards for each issue or item. and to be able to encourage a software engineering agent to follow those links or receive context from those links. So we can imagine a story issue that has descendant task issues and is also this story is also part of maybe an epic issue so we see that there's both ancestors and descendants when we maybe go to render This issue. We would include context from the the epic We would include the issue the story issue itself, its whole description and all the details associated with it. And we'd include context from all the descendant issues, the tasks. into one view so that we have this kind of augmented view of all the different related information that's available for fixing this kind of one issue, such that if we hand this off to a sub-agent, it really should have a lot of context and information to go off of. to be able to start the work, do the work effectively, and then because it's an issue tracker, mark that it's in progress, mark that it's complete, add comments, referencing. any issues that it encountered during implementation, any deviations from the plan? and maybe even references into either the git commit or the jj change revision We can actually add those as annotations or or comments to the issue. So we have a history of all these things that have happened. So that's got a high level what I want to do here and why we're building this thing For me, it's really important that we focus on doing things in kind of a simple and straightforward way using existing technologies. I don't want to get into the details of SQLite database design and transactions and all these kind of um design decisions that we'll need to make and UI interfaces and things like that. We don't want to decide what's the terminology for priority or effort level or which one of these things are uh enumerations versus numbers or whatever So we're going to use Task Warrior version 3 as the Backend issue store. And then we'll build a layer on top of this. in an opinionated way that emphasizes the features that we need and knows how to serialize the data into Task Warrior as well as fetch it and in certain circumstances render it um interviews appropriate for humans, but also interviews appropriate for the software engineering agents where all the context is pulled together and presented in a coherent way and to allow subagents to do a really great job. So I'd like to work with you to hammer out the details, identify the architectural decisions that need to be made. to make it very clear, to develop a very clear requirements document and specification for the software that we're going to build. We're going to explore this together. You're going to ask me a lot of questions to clarify things. We're going to enumerate all of the different commands that we'll need to support, the sort of information that they can display, the interaction modes. We'll come up with a specification And then once we're in a good shape there, we can hand it off to a planning process and to an implementation process. But for right now, we really need to understand at a deep level all the different aspects of this design. So next up I'm going to also do a bit of a brain dump on different considerations and ideas that I have floating around in my mind. Uh, and I'm going to trust you to consider all of the things that I'm saying. Come up with a great understanding of it and ask those key questions that will kind of further tickle out. Really interesting, important. um features for this software.


## Inspiration: Beads

Beads is found here: https://github.com/steveyegge/beads
Tagline: "Beads - A memory upgrade for your coding agent"

I really like the concept - many of the features we'll try to reproduce; however, I don't like that they have to reinvent an issue tracker and all its features. We'll focus on using Taskwarrior v3 and the features it already provides. We want to use `task` fairly idiomatically when possible.

Beads has this intro:

> Beads is a lightweight memory system for coding agents, using a graph-based issue tracker. Four kinds of dependencies work to chain your issues together like beads, making them easy for agents to follow for long distances, and reliably perform complex task streams in the right order.
> 
> Drop Beads into any project where you're using a coding agent, and you'll enjoy an instant upgrade in organization, focus, and your agent's ability to handle long-horizon tasks over multiple compaction sessions. Your agents will use issue tracking with proper epics, rather than creating a swamp of rotten half-implemented markdown plans.

And here are some other things that I like:

> AGENTS.md or CLAUDE.md. That's all there is to it!
> 
> Your coding agent will file and manage issues on your behalf. They'll file things they notice automatically, and you can ask them at any time to add or update issues for you.
>
> Beads gives agents unprecedented long-term planning capability, solving their amnesia when dealing with complex nested plans. They can trivially query the ready work, orient themselves, and land on their feet as soon as they boot up.
> 
> Agents using Beads will no longer silently pass over problems they notice due to lack of context space -- instead, they will automatically file issues for newly-discovered work as they go. No more lost work, ever.

And here's a brief quickstart for how beads works:

```sh
# Create issues during work
bd create "Discovered bug" -t bug -p 0 --json

# Link discovered work back to parent
bd dep add <new-id> <parent-id> --type discovered-from

# Update status
bd update <issue-id> --status in_progress --json

# Complete work
bd close <issue-id> --reason "Implemented" --json
```

## Desired Features

Use the executable name `tw`. Has subcommands, like `tw add`.

Because Taskwarrior may share its tasks among projects, we'll always assign a project to each issue.
Assume the current project name is found in the environment variable `TW_PROJECT_NAME` or falling back to `PROJECT_NAME` or then `"default"`.

There are three types of issues: epic, story, task.
- epics are for high-level goals and projects.
- stories are for smaller, more specific tasks that contribute to an epic.
- tasks are for the smallest units of work that can be completed independently.
We don't have to overspecify when to use each type. Instead, having three layers constrains how we can construct and maintain context for work.
We specify the issue type via... some appropriate mechanism of Taskwarrior. I'm not sure if its a tag/property/or other existing feature.

When I capture an issue that needs to be done, like to change the color of a widget, I'd capture that as a standalone task.
When I work with Claude Code or other system to develop a substantial plan of action, I'd ask it to add an epic to track the effort, and then stories and tasks nested under it.
We might need to develop best practices for what each of these issue types look like.

Taskwarrior supports links via `depends`, like `task 1 modify depends:2`. We use this link to point from child to parent, from task to story, and from story to epic.

Within a tree of issues, tasks will be implemented in ascending order, based on the issue ID. 
So we don't need to add dependency links among siblings whose order is implied by their ID.

The contents of an issue should include some things:
- A title that describes the issue. This will be found in the first line of the issue description, like how git commit messages are structured. When we render various views, we should assume this.
- Then an arbitrary amount of text that describes the issue. We might want to mark some of it as "repeatable", which is the text that we will automatically pull in to other views when stitching together context for a specific task. One idea might be to assume the second paragraph is always repeatable, while all the following paragraphs are not repeatable. This enforces us to slowly reveal more detail, from title, to repeatable, to full detail.
- The text should be markdown

We'll want to support statuses: open, in-progress, and done, or whatever taskwarrior supports.

We want to be able to add comments to issues, which I think Taskwarrior calls annotations (timestamp + content). We want our SWE agents to add comments with information like: deviations from the design, lessons learned, VCS commit references, and any other relevant details.

Let's definitely have the `tw onboard` command that SWE agents will run to learn about the available commands.

Issues should be easily editable. I might start by capturing one sentence, then come back and use voice dictation to rewrite, and then have a SWE agent revise and extend. I don't think we want to build a dedicated IDE/editor for this, but perhaps we can spawn `$EDITOR` to edit a temporary file and write that into the issue.

## Discussion

I used the following prompt to gather feedback:

> So, with this in mind, its time for you to digest the ideas, ultrathink, and reflect on the implications of each decision.
> 
> 1. What are the critical things that we need to decide on architecturally?
> 2. Propose the command/subcommands that `tw` will support, given that its meant to be invoked by SWE agents and humans.
> 3. What questions do you have that would help explore the design space?
> 4. What great ideas for extensions do you have to this concept? Share 5, in three sentences each.

I wrote the results of three experts into ./design-gemini3-1.md ./design-codex-1.md and ./design-claude-1.md.
Let me now collect the things I liked from the three experts.

## Refinements

I agree with the following and they are are accepted, though they possibly need further refinement and discussion:

**A. Hierarchy via UDAs (User Defined Attributes), not `depends`**

*   **Decision:** While you mentioned using `depends` to link Child $\to$ Parent, in Taskwarrior, `depends` implies *blocking execution* (i.e., you cannot complete the child until the parent is done, or vice versa depending on direction). This conflicts with Composition (a Story is "made of" Tasks).
*   **Approach:** We will define a custom UDA `parent` (UUID type).
    *   **Epics** have no parent.
    *   **Stories** have an Epic `parent`.
    *   **Tasks** have a Story `parent`.
*   **Why:** This leaves the standard `depends` field free for actual execution blockers (e.g., "Deploy DB" must happen before "Migrate Data"), while `parent` handles the structural grouping.


**B. Content Storage Strategy**
Taskwarrior's `description` field is optimized for single-line text. Storing a multi-paragraph Markdown document there creates messy terminal output in standard `task` views.

*   **Field 1: `description` (Standard):** Stores the **Title** (Line 1 of your input).
*   **Field 2: `body` (String UDA):** Stores the full Markdown payload (The "Repeatable" summary + the deep details).
*   **Field 3: annotations (Standard):** Stores the agent comments, commit hashes, and "lesson learned" updates.

Alternatives include: (a) store in annotations with a special prefix, (b) use a UDA for extended description, or (c) store descriptions in external files (e.g., .tw/descriptions/<uuid>.md) and reference them. Option (c) is cleanest for markdown editing with $EDITOR, however its outside the Taskwarrior ecosystem. So lets use the UDA `body` as proposed.

**C. The "Augmented View" Resolver**
This is the core "Business Logic" of the `tw` wrapper. When an agent requests to view a specific Task (e.g., ID 50), `tw` must:

1.  Fetch Task 50.
2.  Recursively fetch Parent (Story) and Grandparent (Epic).
3.  **Synthesize Context:**
    *   *Epic:* Title + "Repeatable" Summary (Paragraph 2).
    *   *Story:* Title + "Repeatable" Summary (Paragraph 2).
    *   *Task:* Title + Full Body + Annotations + Sibling Links.
4.  Output this as a single Markdown blob to the Agent.

**D. State Management**

*   **Project:** Mapped to Taskwarrior's `project` attribute.
*   **Type:** Mapped to a UDA `issue_type` (values: `epic`, `story`, `task`).
*   **Status:** Mapped to standard `status` (pending, completed, deleted, waiting). Use `start` / `stop` to track active state.

what side effects to enforce (e.g., mark parent done when all children done?) -> We should not enforce behavior, but we can emit a warning when a parent is closed while a child is still open. And issues should not be auto-closed when their children are done, they must be closed by explicit actions.

validation: guardrails to prevent adding stories under tasks or tasks under epics. Don't over specify whats possible, though.

ID scheme: Taskwarrior uses volatile integer IDs and stable UUIDs. For agent communication, we need stable references. Options: use UUIDs, use short UUID prefixes, or maintain our own sequential IDs in a UDA. -> Yes, lets create stable project IDs like `JIRA-12` for an epic, `JIRA-12-1` for a story, and `JIRA-12-1a` for a task. Put this in a UDA named `task_id` (???). We can get the prefix ("JIRA-") from an environment variable, like `TW_PROJECT_PREFIX` or `PROJECT_PREFIX` or default "epic".

With this in mind, we'd also like to extract from the description/body any referenced issue IDs and add them to a UDA named `tw_refs`.
This should go into a string-typed UDA, and we'll combine the list of issue IDs with a comma, like "PROJ-12,PROJ-15,PROJ-88".
When rendering to the user, we'll have to split this again. We should prefer to order the references by their ID.
Incidentally, we'll need a routine to sort these things correctly, so that `PROJ-1`, `PROJ-2-1`, and `PROJ-12` sort correctly.
We can search on-demand for the backlinks, using a filter query like: `task 'tw_refs ~ PROJ-12' export`
We'll have to have logic that runs after every update to an issue to check if the list of references has changed, and if so, update the UDA.

Project scoping: You mention TW_PROJECT_NAME. We need to decide if this maps to Taskwarrior's project: attribute directly (yes) or if we namespace it differently (no).

**Paragraph 2 "Repeatable" Logic:**
*   You suggested: "Assume the second paragraph is always repeatable."
*   *Scenario:* What if the description is one paragraph? Or a bulleted list?
*   *Alternative:* Can we use a separator? E.g., a `---` line. Everything above `---` is the "Summary/Repeatable Context", everything below is "Implementation Details". This is more robust than counting newlines.
-> Great! Let's use `---` as the separator.


**Sibling Ordering:**

*   You mentioned siblings are implemented in ascending ID order.
*   *Scenario:* You add Task A (ID 10), then Task B (ID 11). Later, you realize you missed a step that needs to happen *before* A. You add Task C (ID 12).
*   *Problem:* ID 12 implies it happens last, but you want it first.
*   *Question:* Should we support a lightweight `priority` or `order` UDA to override ID-based sorting? Or do we trust the Agent/Human to just "deal with it" or re-create tasks?
-> We can encourage the parent task to include in their description/body the order of their children, if necessary. We can always use checkbox lists (`- [ ] foo`) to suggest a task list and imply an order. The context/instructions might say "use the implied order of children by their ID, or use the checkbox list if present".

`TW_PROJECT` will be set by some external tool, like direnv. So nothing we need to do to remain in sync with it or update it.

Good idea: **`tw digest` (Automatic Summarization):**
When a Story is marked `done`, an LLM pass runs over all the child Tasks' "lessons learned" annotations and generates a summary annotation on the Story itself. This bubbles up context so the "Epic" level doesn't lose the details of what happened in the trenches. Likewise with divergences or changes to the plan - we need a summary at the root.

Question: When assembling agent context, do we include annotations and non-repeatable text from ancestors/descendants, or only repeatable slices? Depth limits?
-> Include task ID, title, and repeatable text, but do not include non-repeatable text or annotations. Include from all ancestors and descendents. For the specific input issue, also include the non-repeatable text, as well as any annotations.

idea: correlate VCS commit timestamps with the time slices that each task is open to propose associated work.

idea: describe a `tw handoff` protocol that an agent calls before context compaction. It writes a structured summary (what was done, what remains, blockers encountered) into an annotation, which the next agent session automatically reads when resuming work. I'm not sure this needs to live in `tw` directory, or how it enforces the structure, but maybe just by having it, the agent will use it appropriately.

likewise, there's probably some concept of "templates" that are shown to the agent so they provide the right content in each issue type. I'm not sure if we can do any real validation (unless we accept JSON input), but it can remind the agent how to use the issue type.

idea: Auto-Filing from Code Comments: `tw scan` parses the codebase for TODO(tw): or FIXME(tw): comments and auto-creates linked tasks. I use comments like `TODO(ai)` to invoke Claude Code, and this is even better.

When letting the user edit a temporary file to update an issue, it should look like:

```markdown
Title: Fix the login bug
---
This is the repeatable context (summary).
---
This is the non-repeatable deep dive...
```

We need a strict definition of "Relevant Context" to prevent context explosion.
Traversal Rules:
- Self: Full Title, Full Body, All Annotations.
- Ancestors (up to Root): ID + Title + Status + Repeatable Body
- Descendants (Direct Children only): ID + Title + Status + Repeatable Body
- Siblings: ID + Title + Status + Repeatable Body
- References: ID + Title only
If it turns out these reports are getting too long, then we can tune this. Of course, the agent can always fetch full issue details once it knowns an issue ID. But we should expect some agents to forget, which is why we proactively collect the context for them.

D. Implementation Language

The Decision: Python.
Why:
- Excellent libraries for interacting with LLMs (if we ever add direct LLM calls inside tw).
- Easy string manipulation for the "Augmented View" markdown generation.
- Standard in the AI engineering ecosystem.

We will interact with taskwarrior by shelling out to `task`. But we need to highly localize this code, so it can be carefully audited. Also, that we could potentially swap it out at a later date.
I understand the primary way that we should interact with `task` is through the import/export commands:
Read: subprocess.run(["task", "export", "project:Project", ...]). This returns a massive JSON blob. It is extremely fast and precise.
Write: subprocess.run(["task", "import"], input=json_string). This is the atomic way to update specific fields.

2. "Ready Work" Definition
  How does an agent know what to work on next? What makes an issue "ready"?
  - All blocking dependencies complete?
  - Parent is in-progress?
  - Explicit priority field?
-> they'll always be instructed by the user outside of `tw`. do not assign "next highest priority work" from within `tw`.

3. Task ID Generation
  For PROJ-12-1a style IDs:
  - How do we handle the a, b, c suffix for tasks? What happens after z? -> aa, ab, ac
  - Is the numbering sequential within parent, or global? -> sequential within a parent
  
4. References UDA
    You mention tw_refs for cross-references but note backlink maintenance is complex. Options:
    - Compute backlinks on-demand (no UDA for backlinks)
    - Store bidirectional links and update both on modification
    - Accept eventual inconsistency
-> I'm concerned whether Taskwarrior allows easy computation of the backlinks. Is it indexed somehow? How would we do that, if we only want to record forward links on issues - can we lazily compute backlinks efficiently? Do we need to materialize them (hopefully not)?
-> My initial concern was actually around the effort of: every time the body text changes, we have to re-scan for task ids and update the lists, but i guess thats not actually that hard.

5. Output Modes
  When should --json be assumed vs human-readable? Should agents always get JSON?
-> all tools should emit human text by default, but all tools should also support --json for JSON formatted output. we should use pydantic to define the schemas here. and maybe jinja for formatting?

2. Annotation typing: Should annotations have structured types (lesson, deviation, commit, handoff) or remain freeform text with conventions?
-> this seems like a good idea. lets use those four, as well as "comment" (default, but discouraged with preference to the others).  maybe the annotations are added via `tw record lesson "..."` or `tw record deviation "..."`. then there's `tw handoff ...` and `tw comment ...`

4. Bulk operations: tw add from a markdown file with multiple issues defined? Important for agents creating plans.
-> good, lets consider if a basic DSL would work, like a file that contains leading whitespace/indentation to denote the hierarchy of issues. For example:

```
- epic: user authentication
  - story: login page
  - story: user database
    - task: provision sqlite database
    - task: define schema
    - task: implement login
```
However, we expect there to be multi-line context for most/all issues (incidentally, we really need to describe the best practices), so that won't really work here. but maybe its enough to pre-fill the initial structure? lets support this for a `tw capture` command that spawns `$EDITOR` against a temp file that is then parsed for the issues. This is a useful flow for human users to quickly capture and organize findings during a code review, etc.

* in order to future proof our design and architecture, the implementation should be done such that taskwarrior operations are wrapped in helper routines, and potentially named without taskwarrior-isms, so that we could swap out the backend for our own sqlite database, if we decide to. While we don't plan to do this right away, we should leave the option open.

* an external user will always tell an SWE agent where to work, by pointing to a epic/story/task and asking it to begin there. so there is no need for `tw` to tell the user/agent what the next task is. we should document in what order to pick tasks within the tree (sequentially, depth first), but we don't implement that algorithm ourself.

## Supported Commands

global options:
- fetch project name from: `--project-name`, `TW_PROJECT_NAME`, `PROJECT_NAME`, or "default"
- fetch project prefix from: `--project-prefix`, `TW_PROJECT_PREFIX`, `PROJECT_PREFIX`, or "default"
- `--json` to emit JSON instead of the default human readable text output that uses block characters and syntax highlighted markdown

commands:

`tw onboard`
- print quickstart, examples, and prompt for SWE agent
- cat this into CLAUDE.md or ask SWE agent to execute `tw onboard` when it needs to interact with `tw`.

`tw new <epic|story|task> [--parent <id>] [--title "<title>"] [--body "<body or - for stdin>"]`
- `--title` required
- print project ID to stdout, like `PROJ-1`

`tw delete <id>`
- if there are children, error. those have to be deleted first.
- we prefer not to delete things, this is only to be used in a mistake.

`tw edit <id> [--title "<title>"] [--body "<body or - for stdin>"]`
- or if not `--title` or `--body`, then edit the title and body in `$EDITOR`

`tw capture [- for stdin]`
- read indented DSL for creating epics/stories/tasks
- if not `-`, then edit in `$EDITOR`

`tw view <id>`
- render the given issue and all relevant context
- when the status is stopped and just handed off, highlight the most recent "Handoff" annotation prominently at the top.

`tw digest <id>`
- render the given parent issue and concise summary of its children
- show status, divergences, lessons
- sometime later, we could use an LLM to generate a more concise summary. in the interim, we can hardcode the generation.

`tw start <id>`
- mark task in progress
- add annotation with type "work-begin" and the timestamp
- error if the task is not new or stopped.

`tw blocked <id> --reason "<reason>"`
- mark task as "blocked"
- add annotation with type "blocked", the timestamp, and the reason.
- this indicates that the user has to take some action, answer a question, etc. before the issue can be worked on again. see `tw unblock`.
- error if the issue is not in progress.

`tw unblock <id> --reason "<reason>"`
- mark task as "unblocked"
- add annotation with type "unblocked", the timestamp, and the reason.
- this indicates that the user has taken the necessary action and the issue can be worked on again.
- error if the task is not blocked.

`tw record <lesson|deviation|commit> --message "<message>"`
- add annotation with the given type, the timestamp, and the message.

`tw comment <id> --message "<message>"`
- add annotation with type "comment", the timestamp, and an arbitrary comment (that doesn't fit into another category)

`tw stop`
- error: use `tw handoff` with more detail, instead

`tw handoff <id> --status "<status>" --completed "<things that have been completed>" --remaining "<things that remain to be done>"`
- `--status` (one line, explain why handoff), `--completed` (multiline, checkboxes encouraged) and `--remaining` (multiline, checkboxes encouraged) are required
- this is conceptually like `tw stop` (which does not exist), and makes clear the issue must be picked up by someone else with explicit current status.
- mark task as "stopped"
- add annotation with type "handoff", the timestamp, and the current status of the task.
  - this should contain: what was done, what remains. concatenate completed and remaining sections with headings.
  - blockers should have already been reported in realtime via `tw block`
  - deviations should have already been reported in realtime via `tw record deviation`
  - lessons learned should have already been reported in realtime via `tw record lesson`
- error if the task is not new or stopped.

`tw done <id>`
- mark task as done
- add annotation with type "work-end" and the timestamp
- error if the task is not in progress.

`tw tree`
- show a tree of all epics, stories, and tasks
- don't show epics that are complete (and all descendents are complete)
- closed issues are muted color
- started issues are yellow
- this is the opposite of `tw capture`, use the same format, like:
```
epic: Epic Name (PROJ-1)
  story: Story Name (PROJ-1-1)
    task: Task Name (PROJ-1-1a)
      annotation: Type, Timestamp, Message
      annotation: Type, Timestamp, Message
      annotation: Type, Timestamp, Message
```

`tw scan` (planned)
- ask Claude Code to scan the current code base and add `tw` items for any TODO items found

## Architecture

- language: Python
- Pydantic for data validation and serialization
- Rich for nice text output
- Jinja for rendering human-readable output
- json for machine readable output (rendered from Pydantic models)
- logging for debug/verbose/status messages.
  - rich logging handler to stderr
  - in each file, create a global logger like `logger = logging.getLogger(__name__)`
  - `--verbose` mode sets logging level to DEBUG, enables tracebacks for exceptions. otherwise exceptions printed like `error: failed to open file: ...` to stdout with status code non-zero.
  - provide a `--verbose` flag to enable verbose logging (log level DEBUG), and `--quiet` to disable logging (log level ERROR)
- stdout strictly for command output, either human readable report or json.
  - pass explicit rich.Console instance to any routine that prints. allocate this in the main routine. allocate a global console for writing to STDERR (primarily for status spinners and logging).
- status code non-zero for errors. zero for success.
- use click when the tool supports many subcommands, otherwise argparse when the tool has a single purpose.
- type hints for function signatures.
- google style docstrings for documentation, but don't repeat the type annotation. only explain things that aren't obvious. use the `raises` section to document how the function can fail.
- pytest for testing. 
  - do not use mocks, instead layer and architect the code so that it composes nicely. prefer data/value-oriented designs.
  - we should have close to 100% test coverage.
  - during development, write tests before implementing a function.
  - no dumb tests. create tests that demonstrate functionality
  - keep the test suite fast. use session-scoped fixtures to cache expensive resources. and tempfile directories (contextmanager fixtures) for test-local resources.
- use rich.Spinner with the stderr console and transient=True for any long running operations. use the contextmanager style. its ok to nest these.
- prefer to use dataclasses when possible, and use `@classmethod from_foo(cls, foo)` style constructors
- raise exceptions rather than returning None or error sentinal value. document the exceptions when they're not obvious, especially when they bubble up from callees.
- use pathlib.Path for any file system paths
- use ruff for formatting and linting, mypy for type checking
- functions should be named starting with verbs. `get_` when it returns, `validate_` no return - just raise exception on error, `render_` returns string representation of some combined data, `output_` writes to stdout.

localize taskwarrior interaction to a minimal number of routines, using `task import/export` for manipulations.


taskwarrior UDAs:
- tw_type: string (values: epic, story, task)
- tw_parent: string (tw_id of the parent issue, e.g. PROJ-1-2)
- tw_id: string (The PROJ-1-2a identifier)
- tw_body: string (The full markdown content)
- tw_refs: string (Comma-separated list of referenced tw_ids found in text, sorted)
- tw_status: string (To track handoff vs stop. Values: new, in_progress, stopped, blocked, done). Note: Taskwarrior's native status (pending/completed) is insufficient because handoff keeps a task pending but logically "paused".

The ID Generator Logic:
- Epics: PREFIX-{N} (Find max N of existing epics + 1)
- Stories: PARENT-{N} (Find max N of parent's children + 1)
- Tasks: PARENT-{a-z, aa-zz} (Base 26 logic)

## Discussion: Redux

The following clarifications were made during design review:

### 1. Annotation Storage Format

Annotations use a **bracket prefix convention**: `[type] message`

Example: `[lesson] The database migration needed a retry mechanism`

Rationale:
- Human-readable when viewing raw TaskWarrior output
- Easy to parse programmatically

### 2. Body Structure (Single Separator)

The body field uses a **single `---` separator**:
- Content before `---` is the **repeatable summary** (included in context views)
- Content after `---` is **non-repeatable details** (only shown for the target issue)
- Title is stored separately in TaskWarrior's `description` field

Example body:
```markdown
This is the repeatable context (summary).
---
This is the non-repeatable deep dive with implementation details...
```

### 3. tw_status Values

`tw_status` is our source of truth for issue state. Values:
- `new` — Issue created, not yet started
- `in_progress` — Actively being worked on
- `stopped` — Paused via `tw handoff`, waiting to be resumed
- `blocked` — Cannot proceed, awaiting external action
- `done` — Completed

TaskWarrior's native `status` only changes when we mark `done` (pending → completed). We do not use TaskWarrior's `waiting` status.

### 4. Flexible Hierarchy (Orphans Allowed)

Parent hierarchy is **optional**:
- Tasks can exist without a Story parent
- Stories can exist without an Epic parent
- This supports quick capture workflows

### 5. ID Generation for Orphans

Orphan issues get **hierarchical IDs with reserved parent slots**:
- Creating an orphan task might yield `PROJ-12-1a`
- This implicitly reserves `PROJ-12` (epic slot) and `PROJ-12-1` (story slot)
- Future epics skip past reserved IDs

### 6. Reserved Slots Are Permanent

- Reserved slots cannot be claimed later
- Parent assignment is **immutable** — must be specified at creation time
- No `tw edit --parent` capability
- No `tw add --id` capability either - IDs are allocated by `tw` and not by the user

### 7. tw capture Is Lightweight

`tw capture` only creates structure from the indented DSL:
```
- epic: user authentication
  - story: login page
    - task: implement form
# this is a comment and will be ignored
```

- Lines starting with `#` are ignored (comments)
- Creates issues with titles only (no body content)
- Does not open subsequent editors
- User invokes `tw edit <id>` later to add details

### 8. Handoff Highlighting

In `tw view`, if `tw_status` is `stopped`, the most recent handoff annotation is displayed prominently at the top. No time-based logic — just status-based.

### 9. tw tree Display Rules

- Show full structure within active epics (all stories/tasks, regardless of status)
- Mute completed items (dimmed color)
- Only hide epics where the epic AND all descendants are complete

### 10. References Extraction

- Forward references extracted **on every body write** (create or edit)
- Only match our ID format: `PROJ-\d+(-\d+)?(-[a-z]+)?`
- Backlinks computed on-demand via filter query
- Do not match GitHub issues, commit SHAs, or other patterns

### 11. Editing Active Issues

`tw edit` is allowed **anytime regardless of status**. No need to pause work to refine descriptions. Important changes should still be logged via `tw record deviation`.

### 12. Editor Placeholders and Comments

When spawning `$EDITOR` for new or edited issues:
- Provide placeholder data like `<title>` for new entries
- Support ignored comments prefixed with `# tw:` (like git commit messages)
- Example template:
```
<title>
# tw: Enter the issue title on the first line above
---
<repeatable summary>
# tw: Enter a brief summary above the separator
# tw: This will be shown in context views for related issues
---
<detailed description>
# tw: Enter implementation details below
# tw: Lines starting with '# tw:' will be ignored
```

### 13. Project prefix

Remember project prefix (e.g. `PROJ-`) comes from: `--project-prefix`, `TW_PROJECT_PREFIX`, `PROJECT_PREFIX`, or "default"


### 14. Task reordering 

What if a new task has to inserted between previously created tasks?
-> The parent issue should include repeatable content that specifies the non-standard order of implementation.
