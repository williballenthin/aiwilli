This is a fantastic concept. You are essentially building a **Context-Aware Semantic Layer** over Taskwarrior.

Taskwarrior is notoriously powerful but "flat" by default. By enforcing a strict hierarchy (Epic/Story/Task) and an opinionated context rendering system (The "Augmented View"), you solve the primary issue with Agentic coding: **Context Window Fragmentation.**

Here is the design analysis, proposed architecture, specifications, and the clarifying questions we need to resolve.

---

### 1. Architectural Decisions

To make this work using Taskwarrior v3 (`task`) as the persistent store without "fighting" it, we need to make specific mapping decisions.

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

---

### 2. Proposed Command Specification (`tw`)

The `tw` CLI will wrap `task`. It should detect if output is a TTY (human) or piped (agent) to adjust formatting, or use explicit flags (e.g., `--json`).

#### **Core Lifecycle**

*   **`tw onboard`**
    *   **Role:** System prompt injection.
    *   **Output:** A concise Markdown guide defining the hierarchy, how to parse the output, and how to use the commands. It explains the "Repeatable text" convention.

*   **`tw add <type> "Title"`**
    *   **Args:** `type` (epic/story/task), `Title`.
    *   **Flags:** `--parent <id>` (Required for Story/Task), `--editor` (Opens `$EDITOR` for full body).
    *   **Behavior:** Creates the issue. If `--editor` or no title provided, opens editor. Parses the first line as `description`, rest as `body`.

*   **`tw list [filter]`**
    *   **Role:** High-level overview.
    *   **Human View:** A tree view (ASCII art styling) showing Epics -> Stories -> Tasks.
    *   **Agent View (`--json`):** A flat list of relevant actionable items, including their parent IDs for context lookup.

*   **`tw view <id>`**
    *   **Role:** The **Augmented Context** generator.
    *   **Output:** The hierarchical Markdown blob described in the Architecture section. This is what the Sub-agent consumes to "boot up".

*   **`tw modify <id>`**
    *   **Role:** Update content.
    *   **Behavior:** Opens the combined (Title + Body) in `$EDITOR`. Upon save, splits them back into `description` and `body` UDA.

#### **Workflow & State**

*   **`tw start <id>`** / **`tw stop <id>`**
    *   Standard TW active tracking. Useful for agents to signal "I am working on this right now".

*   **`tw done <id>`**
    *   Marks complete. Optional `-m "Closing comment"` adds an annotation.

*   **`tw comment <id> "text"`**
    *   Adds a timestamped annotation. Used for "Context Rot" mitigation (checkpointing info).

#### **Agent Utilities**

*   **`tw tree`**
    *   Outputs the full ID-based hierarchy of the current project. Essential for the agent to orient itself ("Where does this task fit?").

*   **`tw context <id>`**
    *   Alias for `view` but explicitly formatted for LLM ingestion (perhaps stripping some UI decorations).

---

### 3. Critical Questions to Explore

To write the final spec, I need you to clarify these design forks:

1.  **The `depends` vs. `parent` Dilemma:**
    *   You explicitly asked to use `depends` for child-to-parent links.
    *   *Problem:* If Task A "depends" on Story B, Taskwarrior thinks A cannot be done until B is done. This effectively blocks the child until the parent is finished, which is the exact opposite of how work breaks down (finishing tasks *completes* the story).
    *   *Question:* Are you okay with using a custom UDA (e.g., `parent_id`) to track hierarchy, reserving `depends` for actual execution order (e.g., "Task B cannot start until Task A is done")?

2.  **Paragraph 2 "Repeatable" Logic:**
    *   You suggested: "Assume the second paragraph is always repeatable."
    *   *Scenario:* What if the description is one paragraph? Or a bulleted list?
    *   *Alternative:* Can we use a separator? E.g., a `---` line. Everything above `---` is the "Summary/Repeatable Context", everything below is "Implementation Details". This is more robust than counting newlines.

3.  **Sibling Ordering:**
    *   You mentioned siblings are implemented in ascending ID order.
    *   *Scenario:* You add Task A (ID 10), then Task B (ID 11). Later, you realize you missed a step that needs to happen *before* A. You add Task C (ID 12).
    *   *Problem:* ID 12 implies it happens last, but you want it first.
    *   *Question:* Should we support a lightweight `priority` or `order` UDA to override ID-based sorting? Or do we trust the Agent/Human to just "deal with it" or re-create tasks?

4.  **The "Project" Scope:**
    *   You mentioned `TW_PROJECT_NAME`.
    *   *Question:* If you switch directories/branches, do you want `tw` to automatically detect a configuration file (like `.tw-project`) in the root? This is often safer than relying on ephemeral environment variables that might get lost when a shell restarts or an agent spawns a sub-shell.

---

### 4. Extension Ideas

Here are 5 extensions to enhance this system later:

1.  **`tw digest` (Automatic Summarization):**
    When a Story is marked `done`, an LLM pass runs over all the child Tasks' "lessons learned" annotations and generates a summary annotation on the Story itself. This bubbles up context so the "Epic" level doesn't lose the details of what happened in the trenches.

2.  **Git/JJ Hook Integration (`tw hook`):**
    A `prepare-commit-msg` hook. When you commit code, it checks if `tw` has a currently active task (`tw start`). If so, it prepends the commit message with `[TW-123]` and appends the issue title. Conversely, it adds the commit hash as a comment to the issue automatically.

3.  **Shadow Mode (`tw shadow`):**
    A "Ghost" file system. The agent can write to a file `task_123.plan`. `tw` watches this file. When the file is saved, `tw` automatically updates the body of Task 123. This allows agents to "think" in files (which they are good at) rather than CLI arguments (which can be finicky with escaping quotes).

4.  **Graphviz/Mermaid Export (`tw graph`):**
    Generates a Mermaid JS diagram of the current Epic/Story/Task tree with color-coded status. This can be pasted into the PR description or viewed by the human to quickly grasp the state of a complex feature.

5.  **Context Pruning Strategy:**
    If the "Repeatable Context" (Paragraph 2) of a Story grows too large, `tw` can flag it. We can add a utility `tw refine <id>` where an Agent reads the long context and compresses it back down to a dense token-efficient summary, updating the issue in place.

Let me know your thoughts on the **Hierarchy (UDA vs Depends)** and the **Repeatable Context delimiter**, and we can move to the formal spec.
