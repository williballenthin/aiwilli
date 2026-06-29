import { describe, expect, test } from "bun:test";
import { detectLanguage, expandScope, sliceLines } from "../src/scope.js";

describe("detectLanguage", () => {
  test("classifies by extension", () => {
    expect(detectLanguage("a/b/c.ts")).toBe("brace");
    expect(detectLanguage("x.py")).toBe("python");
    expect(detectLanguage("README.md")).toBe("markdown");
    expect(detectLanguage("notes.txt")).toBe("text");
    expect(detectLanguage("main.rs")).toBe("brace");
  });
});

describe("expandScope: brace", () => {
  const src = [
    "import x from 'x';", // 1
    "", // 2
    "function parse(input: string) {", // 3
    "  const a = 1;", // 4
    "  return a;", // 5
    "}", // 6
    "", // 7
    "function other() {}", // 8
  ].join("\n");

  test("expands a body edit to the whole function + signature", () => {
    const s = expandScope(src, 5, 5, "brace");
    expect(s.start).toBe(3);
    expect(s.end).toBe(6);
    expect(s.label).toContain("function parse");
    expect(sliceLines(src, s.start, s.end)).toContain("return a;");
  });

  test("labels a newly-added top-level declaration the change itself opens", () => {
    const added = "let x = 1;\n\nclass Foo extends Bar {\n  m() { return 1; }\n}\n";
    const s = expandScope(added, 3, 5, "brace");
    expect(s.start).toBe(3);
    expect(s.end).toBe(5);
    expect(s.label).toContain("class Foo");
  });
});

describe("expandScope: python", () => {
  const src = [
    "import os", // 1
    "", // 2
    "def parse(data):", // 3
    "    x = 1", // 4
    "    return x", // 5
    "", // 6
    "def other():", // 7
    "    pass", // 8
  ].join("\n");

  test("expands a body edit to the enclosing def", () => {
    const s = expandScope(src, 4, 4, "python");
    expect(s.start).toBe(3);
    expect(s.end).toBe(5);
    expect(s.label).toBe("def parse(data)");
  });

  test("does not bleed into the next def", () => {
    const s = expandScope(src, 4, 4, "python");
    expect(sliceLines(src, s.start, s.end)).not.toContain("def other");
  });
});

describe("expandScope: markdown", () => {
  const src = [
    "# Title", // 1
    "", // 2
    "## Section A", // 3
    "alpha", // 4
    "beta", // 5
    "", // 6
    "## Section B", // 7
    "gamma", // 8
  ].join("\n");

  test("expands to the enclosing section, stopping at the next heading", () => {
    const s = expandScope(src, 4, 4, "markdown");
    expect(s.start).toBe(3);
    expect(s.end).toBe(5);
    expect(s.label).toBe("## Section A");
    expect(sliceLines(src, s.start, s.end)).not.toContain("Section B");
  });
});

describe("expandScope: caps", () => {
  test("respects maxLines", () => {
    const big = Array.from({ length: 1000 }, (_, i) => `line ${i}`).join("\n");
    const s = expandScope(big, 500, 500, "text", 50);
    expect(s.end - s.start + 1).toBeLessThanOrEqual(51);
  });
});
