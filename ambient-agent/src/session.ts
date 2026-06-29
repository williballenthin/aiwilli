// The ambient session engine: the editor- and agent-agnostic core.
//
// It owns the current state of the watched set, the shadow repo, and the review
// cycle counter. Crucially it contains NO timers: timing (debounce, "agent
// attention returns") lives in the adapter that drives it. This keeps the core
// deterministic and fully testable — tests drive `recordEdit`/`snapshot`/`drain`
// directly and assert on the returned payloads.

import { ShadowRepo } from "./shadow-repo.js";
import { buildContext } from "./context.js";
import type { ContextOptions, ContextPayload, EditEvent } from "./types.js";

export interface SessionOptions extends ContextOptions {
  /** Where to create the shadow repo's temp dir (defaults to runtime/tmp). */
  shadowParentDir?: string;
}

export class AmbientSession {
  private readonly repo: ShadowRepo;
  /** Latest known full content per watched path. */
  private readonly content = new Map<string, string>();
  /** Latest content as of the last committed snapshot (dirty tracking). */
  private dirty = false;
  private cycle = 0;
  private started = false;
  private lastTimestamp = 0;

  constructor(private readonly opts: SessionOptions = {}) {
    this.repo = ShadowRepo.create(opts.shadowParentDir);
  }

  /** Directory of the shadow repo (for debugging/inspection). */
  get shadowDir(): string {
    return this.repo.dir;
  }

  /** Seed the baseline state of the watched set. Call once before edits. */
  start(initial: Iterable<EditEvent> = []): void {
    if (this.started) throw new Error("session already started");
    let ts = 0;
    for (const ev of initial) {
      this.content.set(ev.path, ev.content);
      ts = Math.max(ts, ev.timestamp);
    }
    this.lastTimestamp = ts;
    this.repo.baseline(new Map(this.content), ts);
    this.started = true;
  }

  /**
   * Record an observed edit. Updates the in-memory state but does NOT commit;
   * the adapter calls `snapshot()` on its debounce cadence. Returns true if the
   * content actually changed.
   */
  recordEdit(ev: EditEvent): boolean {
    if (!this.started) throw new Error("session not started");
    this.lastTimestamp = Math.max(this.lastTimestamp, ev.timestamp);
    if (this.content.get(ev.path) === ev.content) return false;
    this.content.set(ev.path, ev.content);
    this.dirty = true;
    return true;
  }

  /** Remove a file from the watched set (deletion). */
  recordDelete(path: string, timestamp: number): boolean {
    if (!this.content.has(path)) return false;
    this.content.delete(path);
    this.dirty = true;
    this.lastTimestamp = Math.max(this.lastTimestamp, timestamp);
    return true;
  }

  /**
   * Commit an incremental snapshot of the current state onto the active drain
   * branch (the "snapshot cadence"). No-op when nothing changed. Returns the
   * snapshot commit sha, or null.
   */
  snapshot(timestamp = this.lastTimestamp): string | null {
    if (!this.started) throw new Error("session not started");
    if (!this.dirty) return null;
    const sha = this.repo.snapshot(new Map(this.content), timestamp);
    this.dirty = false;
    return sha;
  }

  /** Whether there is un-consolidated work to review. */
  get hasPendingReview(): boolean {
    return this.dirty || this.repo.hasPendingDrain;
  }

  /**
   * Drain: the "agent attention returns" boundary. Flush any pending snapshot,
   * consolidate the drain into one net delta, and build the review context.
   * Returns null when there is nothing new to review.
   */
  drain(timestamp = this.lastTimestamp): ContextPayload | null {
    if (!this.started) throw new Error("session not started");
    this.snapshot(timestamp); // capture latest keystrokes into the drain
    const result = this.repo.consolidate(timestamp);
    if (!result) return null;
    this.cycle += 1;
    return buildContext(this.repo.git, this.cycle, result, this.opts);
  }

  /** Release the shadow repo. Idempotent. */
  dispose(): void {
    this.repo.destroy();
  }
}
