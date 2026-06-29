// pi extension: a *minimal wrapper* around the standalone ambient-agent engine.
//
// All substantive logic — file watching, the shadow git repo, snapshot/drain
// cadence, diffing, and context construction — lives in ../src and is reused
// verbatim. This file only does the pi-specific wiring described in the design
// doc (§6):
//
//   * start the watcher in `session_start` (NOT the factory), per pi's rule
//   * drive `review()` (the "agent attention returns" drain) from pi's idle
//     signal, injecting the context as a turn
//   * render commentary into a side widget
//   * clean up in `session_shutdown`
//
// The pi API is declared as a minimal local interface so this file documents
// exactly which primitives it depends on and typechecks without pi installed.
// When wiring into a real pi build, delete these declarations and import the
// real types (`@earendil-works/pi`); the call sites are unchanged.

import { AmbientRunner } from "../src/watcher.js";
import type { ContextPayload } from "../src/types.js";

// ---------------------------------------------------------------------------
// Minimal pi surface (see packages/coding-agent/docs/extensions.md). Loosely
// typed on purpose; replace with the real import when embedding.
// ---------------------------------------------------------------------------
interface PiDeliverOptions {
  triggerTurn?: boolean;
  deliverAs?: "steer" | "followUp" | "nextTurn";
  display?: boolean;
}
interface PiMessage {
  customType: string;
  text: string;
  details?: unknown;
}
interface PiContext {
  mode: "tui" | "headless" | string;
  isIdle(): boolean;
  hasPendingMessages(): boolean;
  ui: {
    setWidget(spec: { id: string; placement: "above" | "below"; render: () => string }): void;
  };
}
interface PiRuntime {
  sendMessage(message: PiMessage, options?: PiDeliverOptions): void;
  on(event: string, handler: (payload: unknown) => void): void;
}
interface ExtensionApi {
  config?: AmbientConfig;
  pi: PiRuntime;
}
interface AmbientConfig {
  /** Files/globs to watch. The wrapper expands these to concrete paths. */
  watch?: string[];
  snapshotDebounceMs?: number;
  task?: string;
  /** When idle and edits are pending, how eagerly to surface a review. */
  posture?: "eager" | "calm";
}

const WIDGET_ID = "ambient-agent-commentary";

/**
 * pi discovers a default-exported factory. Keep it side-effect free: start
 * background resources in `session_start`, not here.
 */
export default function ambientAgent(api: ExtensionApi) {
  const cfg = api.config ?? {};
  const watch = cfg.watch ?? [];
  let runner: AmbientRunner | null = null;
  let lastCommentary = "(ambient agent idle)";

  function renderWidget(): string {
    return `🫧 ambient-agent\n${lastCommentary}`;
  }

  /** Inject one review cycle's context into the pi conversation. */
  function inject(ctx: PiContext, payload: ContextPayload): void {
    const idle = ctx.isIdle();
    api.pi.sendMessage(
      { customType: "ambient-edit", text: payload.prompt, details: payload },
      {
        triggerTurn: idle,
        // Idle → just wake it. Streaming → let it finish, unless the human's
        // attention is clearly stale and fresh edits arrived (steer). We keep
        // the default calm: never hard-interrupt the human's own turn.
        deliverAs: idle ? "nextTurn" : cfg.posture === "eager" ? "steer" : "followUp",
        display: false,
      },
    );
    if (ctx.mode === "tui") {
      lastCommentary = `reviewing ${payload.changes.length} file(s), cycle ${payload.cycle}`;
      ctx.ui.setWidget({ id: WIDGET_ID, placement: "below", render: renderWidget });
    }
  }

  return {
    name: "ambient-agent",

    // Start watcher + shadow repo when the session is live.
    session_start(ctx: PiContext) {
      runner = new AmbientRunner(watch, {
        task: cfg.task,
        snapshotDebounceMs: cfg.snapshotDebounceMs,
        timelineDiffs: true,
        autoReview: false, // pi's idle signal drives the drain, not a timer
        onReview: (payload) => inject(ctx, payload),
      });
      runner.start();
      if (ctx.mode === "tui") {
        ctx.ui.setWidget({ id: WIDGET_ID, placement: "below", render: renderWidget });
      }
    },

    // "The agent's attention returns": when pi goes idle and there are pending
    // edits, drain and inject. This is the inverted-control arbiter point.
    agent_end(ctx: PiContext) {
      if (runner && ctx.isIdle() && runner.hasPendingReview) {
        runner.review();
      }
    },

    session_shutdown() {
      runner?.dispose();
      runner = null;
    },
  };
}
