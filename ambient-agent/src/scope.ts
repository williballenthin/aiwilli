// Language-aware scope expansion.
//
// Given a changed line range, expand it to the enclosing syntactic unit so the
// agent always sees a complete thing (a whole function, class, or doc section)
// rather than an arbitrary slice. This is a dependency-free heuristic chosen so
// the engine stays portable and trivially testable; the interface is the same
// one a tree-sitter backend would implement, so it can be swapped in later
// without touching callers.

export type Language = "brace" | "python" | "markdown" | "text";

const BRACE_EXTS = new Set([
  "js", "jsx", "ts", "tsx", "mjs", "cjs",
  "c", "h", "cc", "cpp", "hpp", "cxx",
  "java", "go", "rs", "swift", "kt", "kts", "cs", "php", "scala",
]);

export function detectLanguage(path: string): Language {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "py" || ext === "pyi") return "python";
  if (ext === "md" || ext === "markdown" || ext === "mdx") return "markdown";
  if (BRACE_EXTS.has(ext)) return "brace";
  return "text";
}

export interface Scope {
  /** 1-based inclusive start/end lines. */
  start: number;
  end: number;
  label?: string;
}

/**
 * Expand the 1-based inclusive range [startLine, endLine] in `content` to its
 * enclosing scope. `maxLines` caps growth so a pathological file can't blow up
 * the payload.
 */
export function expandScope(
  content: string,
  startLine: number,
  endLine: number,
  lang: Language,
  maxLines = 400,
): Scope {
  const lines = content.split("\n");
  const clampedStart = Math.max(1, Math.min(startLine, lines.length));
  const clampedEnd = Math.max(clampedStart, Math.min(endLine, lines.length));

  let scope: Scope;
  switch (lang) {
    case "brace":
      scope = expandBrace(lines, clampedStart, clampedEnd);
      break;
    case "python":
      scope = expandPython(lines, clampedStart, clampedEnd);
      break;
    case "markdown":
      scope = expandMarkdown(lines, clampedStart, clampedEnd);
      break;
    default:
      scope = { start: clampedStart, end: clampedEnd };
  }

  // Enforce the size cap, keeping the change centered.
  if (scope.end - scope.start + 1 > maxLines) {
    const center = Math.floor((clampedStart + clampedEnd) / 2);
    const half = Math.floor(maxLines / 2);
    scope = {
      start: Math.max(1, center - half),
      end: Math.min(lines.length, center + half),
      label: scope.label,
    };
  }
  return scope;
}

/** Extract the post-edit text of a scope (1-based inclusive). */
export function sliceLines(content: string, start: number, end: number): string {
  return content.split("\n").slice(start - 1, end).join("\n");
}

function expandBrace(lines: string[], startLine: number, endLine: number): Scope {
  // Work in absolute character offsets across the whole file.
  const offsets: number[] = [0];
  for (let i = 0; i < lines.length; i++) offsets.push(offsets[i] + lines[i].length + 1);
  const text = lines.join("\n");
  const a = offsets[startLine - 1];
  const b = offsets[endLine]; // exclusive end of last line

  // Walk backward from `a` to find the nearest unmatched '{'.
  let depth = 0;
  let openPos = -1;
  for (let i = a - 1; i >= 0; i--) {
    const ch = text[i];
    if (ch === "}") depth++;
    else if (ch === "{") {
      if (depth === 0) {
        openPos = i;
        break;
      }
      depth--;
    }
  }
  // No enclosing block (e.g. a newly-added top-level declaration). Fall back to
  // the first block the change itself opens, so a new function/class still gets
  // a complete unit + label instead of a bare line range.
  if (openPos < 0) {
    const fwd = text.indexOf("{", a);
    if (fwd >= 0 && fwd < b + 1) openPos = fwd;
    else return { start: startLine, end: endLine };
  }

  // Walk forward from `b` to find the matching '}'.
  depth = 0;
  let closePos = -1;
  for (let i = openPos + 1; i < text.length; i++) {
    const ch = text[i];
    if (ch === "{") depth++;
    else if (ch === "}") {
      if (depth === 0) {
        closePos = i;
        break;
      }
      depth--;
    }
  }
  if (closePos < 0) closePos = text.length - 1;

  const openLine = offsetToLine(offsets, openPos);
  const closeLine = offsetToLine(offsets, closePos);

  // Pull the signature up: contiguous non-blank lines above the brace line
  // (handles multi-line parameter lists and a leading doc comment).
  let sigStart = openLine;
  while (sigStart > 1 && lines[sigStart - 2].trim() !== "") sigStart--;

  const label = lines[openLine - 1].replace(/\s*\{.*$/, "").trim() || lines[openLine - 1].trim();
  return {
    start: Math.min(sigStart, startLine),
    end: Math.max(closeLine, endLine),
    label: label || undefined,
  };
}

function indentOf(line: string): number {
  const m = line.match(/^(\s*)/);
  return m ? m[1].replace(/\t/g, "    ").length : 0;
}

function expandPython(lines: string[], startLine: number, endLine: number): Scope {
  // Find the first non-blank line at/after start to anchor indentation.
  let anchor = startLine;
  while (anchor <= lines.length && lines[anchor - 1].trim() === "") anchor++;
  if (anchor > lines.length) return { start: startLine, end: endLine };
  const anchorIndent = indentOf(lines[anchor - 1]);

  // Walk up to the nearest def/class header with smaller indentation.
  let header = -1;
  for (let i = anchor - 1; i >= 1; i--) {
    const line = lines[i - 1];
    if (line.trim() === "") continue;
    const ind = indentOf(line);
    if (ind < anchorIndent && /^\s*(async\s+def|def|class)\b/.test(line)) {
      header = i;
      break;
    }
    if (ind < anchorIndent && header === -1) {
      // a shallower non-header line bounds us if no header is found above it
    }
  }
  if (header < 0) return { start: startLine, end: endLine };

  const headerIndent = indentOf(lines[header - 1]);
  // Walk down while indented deeper than the header (the body), skipping blanks.
  let end = header;
  for (let i = header + 1; i <= lines.length; i++) {
    const line = lines[i - 1];
    if (line.trim() === "") {
      end = i;
      continue;
    }
    if (indentOf(line) > headerIndent) end = i;
    else break;
  }
  // Trim trailing blank lines.
  while (end > header && lines[end - 1].trim() === "") end--;

  const label = lines[header - 1].trim().replace(/:\s*$/, "");
  return { start: Math.min(header, startLine), end: Math.max(end, endLine), label };
}

function headingLevel(line: string): number {
  const m = line.match(/^(#{1,6})\s/);
  return m ? m[1].length : 0;
}

function expandMarkdown(lines: string[], startLine: number, endLine: number): Scope {
  // Walk up to the nearest heading at/above the change.
  let header = -1;
  for (let i = startLine; i >= 1; i--) {
    if (headingLevel(lines[i - 1]) > 0) {
      header = i;
      break;
    }
  }
  if (header < 0) return { start: startLine, end: endLine };
  const level = headingLevel(lines[header - 1]);

  // Section ends at the next heading of the same or higher level.
  let end = lines.length;
  for (let i = header + 1; i <= lines.length; i++) {
    const lvl = headingLevel(lines[i - 1]);
    if (lvl > 0 && lvl <= level) {
      end = i - 1;
      break;
    }
  }
  while (end > header && lines[end - 1].trim() === "") end--;

  const label = lines[header - 1].trim();
  return { start: Math.min(header, startLine), end: Math.max(end, endLine), label };
}

function offsetToLine(offsets: number[], pos: number): number {
  // offsets[i] is the start offset of line i+1. Binary search.
  let lo = 0;
  let hi = offsets.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (offsets[mid] <= pos) lo = mid;
    else hi = mid - 1;
  }
  return lo + 1;
}
