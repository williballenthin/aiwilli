import { describe, expect, test } from "bun:test";
import { parseNewRanges } from "../src/context.js";

describe("parseNewRanges", () => {
  test("captures a single added block", () => {
    const diff = [
      "diff --git a/f b/f",
      "--- a/f",
      "+++ b/f",
      "@@ -2,0 +3,2 @@",
      "+new line one",
      "+new line two",
    ].join("\n");
    expect(parseNewRanges(diff)).toEqual([{ start: 3, end: 4 }]);
  });

  test("anchors a pure deletion to a line", () => {
    const diff = [
      "@@ -3,2 +3,0 @@",
      "-gone one",
      "-gone two",
    ].join("\n");
    const r = parseNewRanges(diff);
    expect(r.length).toBe(1);
    expect(r[0].start).toBe(3);
  });

  test("handles multiple hunks", () => {
    const diff = [
      "@@ -1,0 +1,1 @@",
      "+a",
      "@@ -10,0 +20,1 @@",
      "+b",
    ].join("\n");
    expect(parseNewRanges(diff)).toEqual([
      { start: 1, end: 1 },
      { start: 20, end: 20 },
    ]);
  });

  test("merges truly contiguous additions", () => {
    const diff = ["@@ -1,0 +5,3 @@", "+a", "+b", "+c"].join("\n");
    expect(parseNewRanges(diff)).toEqual([{ start: 5, end: 7 }]);
  });

  test("keeps changes split by an unchanged line distinct", () => {
    const diff = ["@@ -1,0 +5,1 @@", "+a", " context", "+b"].join("\n");
    // 5..5 then a context line (6) then 7..7 — a one-line gap is not contiguous
    expect(parseNewRanges(diff)).toEqual([
      { start: 5, end: 5 },
      { start: 7, end: 7 },
    ]);
  });
});
