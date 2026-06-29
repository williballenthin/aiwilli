import { afterEach, describe, expect, test } from "bun:test";
import { AmbientSession } from "../src/session.js";
import type { EditEvent } from "../src/types.js";

const sessions: AmbientSession[] = [];
function newSession(): AmbientSession {
  const s = new AmbientSession({ timelineDiffs: true });
  sessions.push(s);
  return s;
}
afterEach(() => {
  for (const s of sessions.splice(0)) s.dispose();
});

function ev(path: string, content: string, t: number): EditEvent {
  return { path, content, timestamp: t };
}

describe("AmbientSession end-to-end", () => {
  test("consolidates many snapshots into one net diff (journey hidden, result shown)", () => {
    const s = newSession();
    s.start([ev("parser.ts", "function parse() {\n  return 0;\n}\n", 1)]);

    // The human stumbles toward the answer over several snapshots.
    s.recordEdit(ev("parser.ts", "function parse() {\n  return 1;\n}\n", 2));
    s.snapshot(2);
    s.recordEdit(ev("parser.ts", "function parse() {\n  return 1;\n}\n\nfunction help() {}\n", 3));
    s.snapshot(3);
    s.recordEdit(ev("parser.ts", "function parse() {\n  return 2;\n}\n\nfunction help() {}\n", 4));
    s.snapshot(4);

    const payload = s.drain(5)!;
    expect(payload).not.toBeNull();
    expect(payload.cycle).toBe(1);

    // Net diff: baseline -> final. The intermediate `return 1` never appears.
    expect(payload.rawDiff).toContain("return 2;");
    expect(payload.rawDiff).not.toContain("return 1;");
    expect(payload.rawDiff).toContain("function help");

    // But the journey is preserved in the timeline (3 snapshots).
    expect(payload.timeline.length).toBe(3);
    expect(payload.timeline[0].summary).toContain("parser.ts");
  });

  test("scope-expands changes to whole functions", () => {
    const s = newSession();
    const base = "function a() {\n  return 1;\n}\n\nfunction b() {\n  return 2;\n}\n";
    s.start([ev("m.ts", base, 1)]);
    // edit only inside b()
    s.recordEdit(ev("m.ts", "function a() {\n  return 1;\n}\n\nfunction b() {\n  return 99;\n}\n", 2));
    const payload = s.drain(3)!;

    const change = payload.changes.find((c) => c.path === "m.ts")!;
    expect(change.status).toBe("modified");
    expect(change.hunks.length).toBe(1);
    const hunk = change.hunks[0];
    expect(hunk.scope).toContain("function b");
    expect(hunk.code).toContain("return 99;");
    expect(hunk.code).not.toContain("function a");
  });

  test("returns null when nothing changed since last drain", () => {
    const s = newSession();
    s.start([ev("a.ts", "let x = 1;\n", 1)]);
    expect(s.drain(2)).toBeNull();
  });

  test("multiple drains advance the cycle and only report new work", () => {
    const s = newSession();
    s.start([ev("a.py", "def f():\n    return 1\n", 1)]);

    s.recordEdit(ev("a.py", "def f():\n    return 2\n", 2));
    const first = s.drain(3)!;
    expect(first.cycle).toBe(1);
    expect(first.rawDiff).toContain("return 2");

    s.recordEdit(ev("a.py", "def f():\n    return 2\n\ndef g():\n    return 3\n", 4));
    const second = s.drain(5)!;
    expect(second.cycle).toBe(2);
    // second drain only reports the new function, not the earlier change
    expect(second.rawDiff).toContain("def g");
    expect(second.rawDiff).not.toContain("return 1");
  });

  test("infers in-progress vs complete (intent posture)", () => {
    const s = newSession();
    s.start([ev("w.ts", "function done() {\n  return 1;\n}\n", 1)]);
    // leave an unbalanced brace => in-progress
    s.recordEdit(ev("w.ts", "function done() {\n  return 1;\n}\nfunction wip() {\n", 2));
    const payload = s.drain(3)!;
    expect(payload.intent.looksComplete).toBe(false);
    expect(payload.intent.posture).not.toBe("review");
    expect(payload.intent.reasons.join(" ")).toContain("brace");
  });

  test("treats touching tests as a review-ready signal", () => {
    const s = newSession();
    s.start([
      ev("src/m.ts", "export const a = 1;\n", 1),
      ev("test/m.test.ts", "test('x', () => {});\n", 1),
    ]);
    s.recordEdit(ev("src/m.ts", "export const a = 2;\n", 2));
    s.recordEdit(ev("test/m.test.ts", "test('x', () => { expect(2).toBe(2); });\n", 2));
    const payload = s.drain(3)!;
    expect(payload.intent.reasons.join(" ")).toContain("tests");
  });

  test("handles a brand-new file (added status)", () => {
    const s = newSession();
    s.start([ev("a.ts", "let x = 1;\n", 1)]);
    s.recordEdit(ev("b.ts", "function fresh() {\n  return 7;\n}\n", 2));
    const payload = s.drain(3)!;
    const added = payload.changes.find((c) => c.path === "b.ts")!;
    expect(added.status).toBe("added");
    expect(payload.prompt).toContain("b.ts");
  });

  test("works on prose: expands a Markdown edit to its section", () => {
    const s = newSession();
    const base = "# Doc\n\n## Goals\nship it\n\n## Risks\nnone\n";
    s.start([ev("docs/plan.md", base, 1)]);
    s.recordEdit(ev("docs/plan.md", "# Doc\n\n## Goals\nship it fast and safely\n\n## Risks\nnone\n", 2));
    const payload = s.drain(3)!;
    const change = payload.changes.find((c) => c.path === "docs/plan.md")!;
    expect(change.hunks[0].scope).toBe("## Goals");
    expect(change.hunks[0].code).toContain("ship it fast and safely");
    expect(change.hunks[0].code).not.toContain("## Risks");
  });

  test("renders a layered prompt with task at top and output contract at bottom", () => {
    const s = newSession();
    s.start([ev("a.ts", "let x = 1;\n", 1)]);
    s.recordEdit(ev("a.ts", "let x = 2;\n", 2));
    const p = s.drain(3)!;
    expect(p.prompt.indexOf("# Task")).toBe(0);
    expect(p.prompt).toContain("# Net change since you last looked");
    expect(p.prompt.lastIndexOf("# Output")).toBeGreaterThan(p.prompt.indexOf("# Net change"));
  });
});
