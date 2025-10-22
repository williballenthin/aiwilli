---
name: working-with-jj
description: Jujutsu (jj) version control cheatsheet - viewing history, making commits, diffs, and descriptions
---

# Working with Jujutsu (jj)

Quick reference for common Jujutsu operations used in development workflows.

Jujutsu is a Git-compatible VCS that eliminates staging and treats your working directory as an actual commit that continuously updates.

## Detecting Jujutsu

Check if the project uses jj:
```bash
test -d .jj && echo "jj" || echo "not jj"
```

## Key Concepts

- **`@`** - Your current working copy (like Git's HEAD)
- **`@-`** - Parent of working copy (like Git's HEAD~1)
- **No staging area** - Changes are automatically recorded
- **Change IDs** - Stable identifiers that survive rebases
- **Commit IDs** - Traditional hashes compatible with Git

## Recommended Workflow

**The jj way:**
1. Make edits to files
2. Run `jj new` to create a new commit (repeat for every logical change)
3. After a series of commits, go back and review with `jj log`
4. Add meaningful descriptions with `jj describe <change-id> -m "description"`
5. Squash related commits together with `jj squash`

This workflow creates fine-grained history as you work, then lets you organize it meaningfully afterward.

## Viewing the Log

**Show recent commits:**
```bash
jj log -r @~10..@
```

**Show full log:**
```bash
jj log
```

**Show specific commit:**
```bash
jj show <change-id>
```

**Show log with more detail:**
```bash
jj log --stat
```

## Viewing Diffs

**See current changes:**
```bash
jj diff
```

**Diff specific commit:**
```bash
jj diff -r <change-id>
```

**Diff between two commits:**
```bash
jj diff --from <base> --to <head>
```

**Git-style diff output:**
```bash
jj diff --git
```

**Show what changed in a commit:**
```bash
jj show <change-id>
```

## Getting Commit References

**Current commit ID:**
```bash
jj log -r @ -T commit_id --no-graph
```

**Parent commit ID:**
```bash
jj log -r @- -T commit_id --no-graph
```

**Get change ID:**
```bash
jj log -r @ -T change_id --no-graph
```

**Revset references:**
- `@` - working copy commit
- `@-` - parent commit
- `@--` - grandparent commit
- `root()` - the root commit
- `trunk()` - main branch tip

## Making Commits

**Create new commit (after editing files):**
```bash
jj new
```

**Create new commit with message:**
```bash
jj new -m "commit message"
```

**Commit current changes with description:**
```bash
jj describe -m "commit message"
jj new
```

**Note:** Unlike Git, jj automatically tracks file changes. No `add` command needed!

## Setting Descriptions

**Set description for current commit:**
```bash
jj describe -m "new description"
```

**Set description in editor:**
```bash
jj describe
```

**Set description for specific commit:**
```bash
jj describe <change-id> -m "description"
```

## Organizing Commits

**Squash current commit into parent:**
```bash
jj squash
```

**Squash specific commit into its parent:**
```bash
jj squash -r <change-id>
```

**Squash current commit into a specific commit:**
```bash
jj squash --into <target-change-id>
```

**Move changes from one commit to another:**
```bash
jj move --from <source> --to <target>
```

**Edit an earlier commit:**
```bash
jj edit <change-id>
```
(Make changes, then `jj new` to continue)

**Split a commit into multiple:**
```bash
jj split <change-id>
```

## Status Information

**See current status:**
```bash
jj status
```

**See bookmark (branch) info:**
```bash
jj bookmark list
```

## Common Patterns

**Get range for code review:**
```bash
BASE_SHA=$(jj log -r @- -T commit_id --no-graph)
HEAD_SHA=$(jj log -r @ -T commit_id --no-graph)
echo "Reviewing: $BASE_SHA..$HEAD_SHA"
```

**Compare against trunk:**
```bash
jj diff --from trunk() --to @
```

**See files changed:**
```bash
jj diff --summary
```

## Git Interoperability

**Fetch from Git remote:**
```bash
jj git fetch
```

**Push to Git remote:**
```bash
jj git push
```

**Export to colocated Git repo:**
```bash
jj git export
```

## Workflow Comparison

| Task | Git | Jujutsu |
|------|-----|---------|
| Make commit | `git add . && git commit -m "msg"` | `jj describe -m "msg" && jj new` |
| See changes | `git diff` | `jj diff` |
| View history | `git log` | `jj log` |
| Get current SHA | `git rev-parse HEAD` | `jj log -r @ -T commit_id --no-graph` |
| Amend commit | `git commit --amend` | `jj describe` (then `jj new` if done) |
| No staging | (N/A) | Automatic! |

## Why Jujutsu?

- **No staging area confusion** - Edit files, they're tracked
- **No detached HEAD** - All commits are reachable
- **Conflict tracking** - Conflicts are first-class objects
- **Safe experimentation** - Easy to undo anything
- **Git compatible** - Works with GitHub, GitLab, etc.
