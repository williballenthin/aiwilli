// The shadow repository: a throwaway, working-tree-free git repo that records
// the editing session as a two-tier history.
//
//   main:     baseline ----------- M1 ----------- M2 ...   (consolidated drains)
//                                   |              |
//   drain-1:  *--*--*--*------------+              |
//             (debounced snapshots)                |
//   drain-2:                        *--*--*--------+
//
// Each `*` is an incremental snapshot taken while the human edits. Each `Mn` is
// a --no-ff merge consolidating one drain into a single net delta on `main`.
// `git log --first-parent main` is the clean net timeline; traversing a merge's
// second parent recovers the keystroke journey. All commits are built with
// `commit-tree` from blobs written via stdin, so no working tree is ever
// created or touched — safe while a human edits the same files live.

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Git } from "./git.js";

export interface Snapshot {
  sha: string;
  parent: string;
  timestamp: number;
}

export interface ConsolidateResult {
  /** Net-diff endpoints: diff(from, to) is the consolidated change. */
  from: string;
  to: string;
  /** The merge commit on main. */
  merge: string;
  /** Incremental snapshots that fed this drain (oldest first). */
  snapshots: Snapshot[];
}

export class ShadowRepo {
  readonly git: Git;
  private mainTip = "";
  private drainCounter = 0;
  private drain: {
    name: string;
    base: string;
    tip: string;
    snapshots: Snapshot[];
  } | null = null;

  private constructor(
    readonly dir: string,
    private readonly owned: boolean,
  ) {
    this.git = new Git({
      gitDir: join(dir, "shadow.git"),
      indexFile: join(dir, "shadow.index"),
    });
  }

  /** Create a fresh shadow repo in a temp dir (auto-removed on `destroy`). */
  static create(parentDir?: string): ShadowRepo {
    const base = parentDir ?? process.env.XDG_RUNTIME_DIR ?? tmpdir();
    const dir = mkdtempSync(join(base, "ambient-shadow-"));
    const repo = new ShadowRepo(dir, true);
    repo.git.run(["init", "--quiet", "--bare", join(dir, "shadow.git")]);
    return repo;
  }

  /** Tip of the net (first-parent) history. */
  get head(): string {
    return this.mainTip;
  }

  /** Whether a drain is currently accumulating snapshots. */
  get hasPendingDrain(): boolean {
    return this.drain !== null;
  }

  private buildTree(files: Map<string, string>): string {
    this.git.readTree(); // empty the index
    for (const [path, content] of files) {
      const sha = this.git.hashObject(path, content);
      this.git.stageBlob(path, sha);
    }
    return this.git.writeTree();
  }

  /** Record the initial state of the watched set as the baseline commit. */
  baseline(files: Map<string, string>, timestamp: number): string {
    const tree = this.buildTree(files);
    const commit = this.git.commitTree(tree, [], `baseline @${timestamp}`);
    this.git.updateRef("refs/heads/main", commit);
    this.mainTip = commit;
    return commit;
  }

  /**
   * Capture an incremental snapshot of the full watched set onto the active
   * drain branch (starting one off `main` if needed). Returns the commit sha,
   * or null if the content is identical to the previous snapshot/baseline.
   */
  snapshot(files: Map<string, string>, timestamp: number): string | null {
    const tree = this.buildTree(files);
    const parent = this.drain ? this.drain.tip : this.mainTip;
    // Skip no-op snapshots: identical tree to the parent commit.
    if (parent && this.git.treeOf(parent) === tree) return null;

    const commit = this.git.commitTree(tree, [parent], `snapshot @${timestamp}`);
    if (!this.drain) {
      this.drainCounter += 1;
      const name = `refs/heads/drain-${this.drainCounter}`;
      this.git.updateRef(name, commit);
      this.drain = { name, base: this.mainTip, tip: commit, snapshots: [] };
    } else {
      this.git.updateRef(this.drain.name, commit);
      this.drain.tip = commit;
    }
    this.drain.snapshots.push({ sha: commit, parent, timestamp });
    return commit;
  }

  /**
   * Consolidate the active drain into a single net delta on `main` via a
   * --no-ff merge (built with commit-tree, tree = drain tip's tree, so no
   * conflicts and no working tree). Returns null when no drain is pending.
   */
  consolidate(timestamp: number): ConsolidateResult | null {
    if (!this.drain) return null;
    const drain = this.drain;
    const tree = this.git.treeOf(drain.tip);
    const merge = this.git.commitTree(
      tree,
      [this.mainTip, drain.tip],
      `consolidate drain @${timestamp}`,
    );
    const from = this.mainTip;
    this.git.updateRef("refs/heads/main", merge);
    this.git.deleteRef(drain.name); // commits stay reachable via merge^2
    this.mainTip = merge;
    this.drain = null;
    return { from, to: merge, merge, snapshots: drain.snapshots };
  }

  /** Remove the shadow repo's temp dir. Idempotent. */
  destroy(): void {
    if (this.owned) {
      try {
        rmSync(this.dir, { recursive: true, force: true });
      } catch {
        // best-effort cleanup
      }
    }
  }
}
