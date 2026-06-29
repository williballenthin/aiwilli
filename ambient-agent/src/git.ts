// Thin wrapper around the git CLI for the shadow repository.
//
// Every invocation runs against an explicitly-pointed bare repo + private index
// file so the shadow repo is fully isolated from the project's real `.git` and
// never requires (or touches) a working tree.

import { execFileSync } from "node:child_process";

export interface GitEnv {
  /** GIT_DIR — the bare shadow repository. */
  gitDir: string;
  /** GIT_INDEX_FILE — a private index, decoupled from any working tree. */
  indexFile: string;
}

export class Git {
  constructor(private readonly env: GitEnv) {}

  private baseEnv(): NodeJS.ProcessEnv {
    return {
      ...process.env,
      GIT_DIR: this.env.gitDir,
      GIT_INDEX_FILE: this.env.indexFile,
      // Deterministic identity + dates so commits are reproducible in tests.
      GIT_AUTHOR_NAME: "ambient-agent",
      GIT_AUTHOR_EMAIL: "ambient@localhost",
      GIT_COMMITTER_NAME: "ambient-agent",
      GIT_COMMITTER_EMAIL: "ambient@localhost",
    };
  }

  /** Run git with string output. `input` is piped to stdin when provided. */
  run(args: string[], input?: string | Buffer): string {
    return execFileSync("git", args, {
      env: this.baseEnv(),
      input,
      encoding: "utf8",
      maxBuffer: 256 * 1024 * 1024,
    }).toString();
  }

  /** Run git tolerating a non-zero exit (e.g. `diff` returning 1). */
  runAllowFail(args: string[], input?: string | Buffer): { stdout: string; code: number } {
    try {
      return { stdout: this.run(args, input), code: 0 };
    } catch (err: unknown) {
      const e = err as { status?: number; stdout?: Buffer | string };
      const out = e.stdout ? e.stdout.toString() : "";
      return { stdout: out, code: e.status ?? 1 };
    }
  }

  /** Write `content` as a blob with the given path hint; returns its sha. */
  hashObject(path: string, content: string): string {
    return this.run(["hash-object", "-w", "--stdin", "--path", path], content).trim();
  }

  /** Stage a blob at `path` into the private index via cacheinfo. */
  stageBlob(path: string, sha: string): void {
    this.run(["update-index", "--add", "--cacheinfo", `100644,${sha},${path}`]);
  }

  /** Reset the private index, optionally to a tree. */
  readTree(tree?: string): void {
    if (tree) this.run(["read-tree", tree]);
    else this.run(["read-tree", "--empty"]);
  }

  /** Write the current index out as a tree object; returns the tree sha. */
  writeTree(): string {
    return this.run(["write-tree"]).trim();
  }

  /** Create a commit object for `tree` with the given parents (no checkout). */
  commitTree(tree: string, parents: string[], message: string): string {
    const args = ["commit-tree", tree];
    for (const p of parents) args.push("-p", p);
    args.push("-m", message);
    return this.run(args).trim();
  }

  updateRef(ref: string, sha: string): void {
    this.run(["update-ref", ref, sha]);
  }

  deleteRef(ref: string): void {
    this.run(["update-ref", "-d", ref]);
  }

  revParse(rev: string): string {
    return this.run(["rev-parse", rev]).trim();
  }

  treeOf(rev: string): string {
    return this.run(["rev-parse", `${rev}^{tree}`]).trim();
  }

  refExists(ref: string): boolean {
    return this.runAllowFail(["rev-parse", "--verify", "--quiet", ref]).code === 0;
  }

  /** Unified diff between two revisions, restricted to `paths` if given. */
  diff(
    from: string,
    to: string,
    paths?: string[],
    opts: { context?: number; functionContext?: boolean } = {},
  ): string {
    const args = ["diff", `--unified=${opts.context ?? 3}`, "--no-color"];
    if (opts.functionContext) args.push("--function-context");
    args.push(from, to);
    if (paths && paths.length) args.push("--", ...paths);
    return this.runAllowFail(args).stdout;
  }

  /** Name-status between two revisions: [{status, path}]. */
  nameStatus(from: string, to: string): Array<{ status: string; path: string }> {
    const out = this.runAllowFail(["diff", "--name-status", "--no-color", from, to]).stdout;
    const rows: Array<{ status: string; path: string }> = [];
    for (const line of out.split("\n")) {
      if (!line.trim()) continue;
      const [status, ...rest] = line.split("\t");
      rows.push({ status: status.trim(), path: rest.join("\t").trim() });
    }
    return rows;
  }

  /** First-parent commit shas from `to` back to (excluding) `from`. */
  firstParentLog(from: string, to: string): string[] {
    const out = this.runAllowFail([
      "log",
      "--first-parent",
      "--format=%H",
      `${from}..${to}`,
    ]).stdout;
    return out.split("\n").map((s) => s.trim()).filter(Boolean);
  }

  /** Read a file's content at a revision (empty string if absent). */
  show(rev: string, path: string): string {
    const r = this.runAllowFail(["show", `${rev}:${path}`]);
    return r.code === 0 ? r.stdout : "";
  }
}
