// Filesystem adapter + timing policy.
//
// The engine (AmbientSession) is timing-free; everything time-based lives here
// so it can be swapped. The standalone runner approximates "agent attention
// returns" with a quiet-period trigger; the pi wrapper instead drives `drain()`
// from pi's idle/turn signals while reusing the same debounced-snapshot logic.

import { readFileSync, statSync, watch as fsWatch, type FSWatcher } from "node:fs";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { AmbientSession, type SessionOptions } from "./session.js";
import type { ContextPayload, EditEvent } from "./types.js";

/**
 * Derive a clean, repo-internal key for a watched path. git's index rejects
 * absolute paths and `..`, so we prefer a cwd-relative path and otherwise strip
 * leading slashes. The key is stable and also used as the display path.
 */
export function toKey(p: string): string {
  const abs = resolve(p);
  let rel = relative(process.cwd(), abs);
  if (rel === "" || rel.startsWith("..") || isAbsolute(rel)) {
    rel = abs.replace(/^\/+/, "");
  }
  return rel.split(sep).join("/");
}

export interface RunnerOptions extends SessionOptions {
  /** Quiet period before an edit is committed as a snapshot (ms). */
  snapshotDebounceMs?: number;
  /**
   * Quiet period with no edits before a review is triggered (ms). This stands
   * in for "the agent's attention returns" in the standalone runner.
   */
  reviewQuietMs?: number;
  /**
   * When false, the runner never triggers reviews on its own; the embedder
   * drives `review()` (e.g. the pi wrapper drives it from pi's idle signal).
   * It still watches files and snapshots on the debounce cadence. Default true.
   */
  autoReview?: boolean;
  /** Called once per review cycle with the constructed context. */
  onReview: (payload: ContextPayload) => void;
}

function readSafe(path: string): string | null {
  try {
    if (!statSync(path).isFile()) return null;
    return readFileSync(path, "utf8");
  } catch {
    return null;
  }
}

/**
 * Watches a fixed set of files and drives an AmbientSession with a debounced
 * snapshot cadence and a quiet-period review cadence.
 */
export class AmbientRunner {
  private readonly session: AmbientSession;
  private readonly watchers: FSWatcher[] = [];
  private snapshotTimer: ReturnType<typeof setTimeout> | null = null;
  private reviewTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly snapshotMs: number;
  private readonly reviewMs: number;
  private readonly autoReview: boolean;
  private readonly onReview: (p: ContextPayload) => void;
  private disposed = false;

  constructor(
    private readonly paths: string[],
    opts: RunnerOptions,
  ) {
    this.snapshotMs = opts.snapshotDebounceMs ?? 1500;
    this.reviewMs = opts.reviewQuietMs ?? 8000;
    this.autoReview = opts.autoReview ?? true;
    this.onReview = opts.onReview;
    this.session = new AmbientSession(opts);
  }

  /** Whether there is un-reviewed work pending (for embedder idle checks). */
  get hasPendingReview(): boolean {
    return this.session.hasPendingReview;
  }

  get shadowDir(): string {
    return this.session.shadowDir;
  }

  /** Seed baselines from current file contents and begin watching. */
  start(now = Date.now()): void {
    const initial: EditEvent[] = [];
    for (const p of this.paths) {
      const abs = resolve(p);
      const content = readSafe(abs);
      if (content !== null) initial.push({ path: toKey(p), content, timestamp: now });
    }
    this.session.start(initial);

    for (const p of this.paths) {
      const abs = resolve(p);
      const key = toKey(p);
      try {
        const w = fsWatch(abs, () => this.onFsEvent(key, abs));
        this.watchers.push(w);
      } catch {
        // file may not exist yet; ignore
      }
    }
  }

  /** Manually feed an edit (used by the simulate path and by the pi wrapper). */
  feed(ev: EditEvent): void {
    if (this.session.recordEdit(ev)) this.scheduleSnapshot(ev.timestamp);
  }

  private onFsEvent(path: string, abs: string): void {
    const content = readSafe(abs);
    const ts = Date.now();
    if (content === null) {
      this.session.recordDelete(path, ts);
    } else {
      this.session.recordEdit({ path, content, timestamp: ts });
    }
    this.scheduleSnapshot(ts);
  }

  private scheduleSnapshot(ts: number): void {
    if (this.snapshotTimer) clearTimeout(this.snapshotTimer);
    this.snapshotTimer = setTimeout(() => {
      this.session.snapshot(ts);
    }, this.snapshotMs);

    if (this.autoReview) {
      if (this.reviewTimer) clearTimeout(this.reviewTimer);
      this.reviewTimer = setTimeout(() => this.review(Date.now()), this.reviewMs);
    }
  }

  /** Force a review now (the standalone analogue of "attention returns"). */
  review(now = Date.now()): ContextPayload | null {
    const payload = this.session.drain(now);
    if (payload) this.onReview(payload);
    return payload;
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    if (this.snapshotTimer) clearTimeout(this.snapshotTimer);
    if (this.reviewTimer) clearTimeout(this.reviewTimer);
    for (const w of this.watchers) w.close();
    this.session.dispose();
  }
}
