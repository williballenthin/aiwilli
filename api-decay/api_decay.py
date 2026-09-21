#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "rich>=13.0",
# ]
# ///
"""Show how the public Python API surface changed between main and the current branch."""

from __future__ import annotations

import argparse
import ast
import difflib
import fnmatch
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.markup import escape

logger = logging.getLogger(__name__)

stderr_console = Console(stderr=True)


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------

def git_merge_base(base: str = "main") -> str:
    result = subprocess.run(
        ["git", "merge-base", base, "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


@dataclass
class GitFileChange:
    status: str
    path: str
    old_path: str | None = None


def git_diff_files(base_ref: str) -> list[GitFileChange]:
    result = subprocess.run(
        ["git", "diff", "--name-status", "-M", base_ref, "HEAD", "--", "*.py"],
        capture_output=True, text=True, check=True,
    )
    changes: list[GitFileChange] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R"):
            changes.append(GitFileChange(status="R", path=parts[2], old_path=parts[1]))
        elif status in ("A", "C"):
            changes.append(GitFileChange(status="A", path=parts[1]))
        elif status == "D":
            changes.append(GitFileChange(status="D", path=parts[1]))
        elif status == "M":
            changes.append(GitFileChange(status="M", path=parts[1]))
    return changes


def git_show(ref: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def git_toplevel() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    )
    return Path(result.stdout.strip())


# ---------------------------------------------------------------------------
# AST -> public API stub rendering
# ---------------------------------------------------------------------------

API_DECORATORS = frozenset({
    "property", "staticmethod", "classmethod",
    "abstractmethod", "overload",
    "dataclass", "dataclasses.dataclass",
    "attrs.define", "attr.s", "attr.attrs",
})

DUNDER_ALLOWLIST = frozenset({
    "__init__", "__new__", "__del__",
    "__enter__", "__exit__", "__aenter__", "__aexit__",
    "__call__", "__getitem__", "__setitem__", "__delitem__",
    "__contains__", "__len__", "__iter__", "__next__",
    "__aiter__", "__anext__",
    "__hash__", "__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__",
    "__add__", "__radd__", "__sub__", "__rsub__",
    "__mul__", "__rmul__", "__truediv__", "__floordiv__",
    "__mod__", "__pow__", "__matmul__",
    "__and__", "__or__", "__xor__", "__invert__",
    "__neg__", "__pos__", "__abs__",
    "__repr__", "__str__", "__format__", "__bytes__",
    "__bool__", "__int__", "__float__", "__complex__", "__index__",
    "__get__", "__set__", "__delete__", "__set_name__",
    "__init_subclass__", "__class_getitem__",
    "__post_init__",
})


def _is_public(name: str, is_class_member: bool = False) -> bool:
    if name.startswith("__") and name.endswith("__"):
        return is_class_member and name in DUNDER_ALLOWLIST
    return not name.startswith("_")


def _unparse_safe(node: ast.expr) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "..."


def _simplify_default(node: ast.expr) -> str:
    match node:
        case ast.Constant():
            return _unparse_safe(node)
        case ast.Name():
            return node.id
        case ast.Attribute():
            return _unparse_safe(node)
        case ast.List() | ast.Tuple() | ast.Set() | ast.Dict() if not (
            getattr(node, "elts", None) or getattr(node, "keys", None)
        ):
            return _unparse_safe(node)
        case _:
            return "..."


def _render_decorator(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name):
            dec_name = name
        case ast.Attribute(attr=name):
            dec_name = _unparse_safe(node)
        case ast.Call(func=ast.Name(id=name)):
            dec_name = name
        case ast.Call(func=ast.Attribute() as attr):
            dec_name = _unparse_safe(attr)
        case _:
            dec_name = _unparse_safe(node)

    base = dec_name.split("(")[0]
    if base in API_DECORATORS or any(base.endswith(f".{a}") for a in API_DECORATORS):
        if isinstance(node, ast.Call) and node.args or (isinstance(node, ast.Call) and node.keywords):
            return f"@{_unparse_safe(node)}"
        return f"@{dec_name}"
    return None


def _render_arg(arg: ast.arg, default: ast.expr | None = None) -> str:
    parts = [arg.arg]
    if arg.annotation:
        parts.append(f": {_unparse_safe(arg.annotation)}")
    if default is not None:
        parts.append(f" = {_simplify_default(default)}")
    return "".join(parts)


def _render_arguments(args: ast.arguments) -> str:
    parts: list[str] = []

    num_args = len(args.args)
    num_defaults = len(args.defaults)
    non_default_count = num_args - num_defaults

    for i, arg in enumerate(args.args):
        default_idx = i - non_default_count
        default = args.defaults[default_idx] if default_idx >= 0 else None
        parts.append(_render_arg(arg, default))

    if args.vararg:
        parts.append(f"*{_render_arg(args.vararg)}")
    elif args.kwonlyargs:
        parts.append("*")

    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        parts.append(_render_arg(arg, default))

    if args.kwarg:
        parts.append(f"**{_render_arg(args.kwarg)}")

    return ", ".join(parts)


def _split_args(args_str: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in args_str:
        if char in "([{":
            depth += 1
            current.append(char)
        elif char in ")]}":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    remainder = "".join(current).strip()
    if remainder:
        parts.append(remainder)
    return parts


def _wrap_signature(prefix: str, args_str: str, suffix: str, indent: str, width: int = 88) -> list[str]:
    one_liner = f"{indent}{prefix}({args_str}){suffix}: ..."
    if len(one_liner) <= width:
        return [one_liner]

    arg_indent = indent + "    "
    parts = _split_args(args_str)
    lines = [f"{indent}{prefix}("]
    for i, part in enumerate(parts):
        comma = "," if i < len(parts) - 1 else ","
        lines.append(f"{arg_indent}{part}{comma}")
    lines.append(f"{indent}){suffix}: ...")
    return lines


def _render_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    indent: str = "",
    is_class_member: bool = False,
) -> list[str]:
    if not _is_public(node.name, is_class_member):
        return []

    lines: list[str] = []

    for dec in node.decorator_list:
        rendered = _render_decorator(dec)
        if rendered:
            lines.append(f"{indent}{rendered}")

    async_prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    returns = f" -> {_unparse_safe(node.returns)}" if node.returns else ""
    sig = _render_arguments(node.args)
    prefix = f"{async_prefix}def {node.name}"
    lines.extend(_wrap_signature(prefix, sig, returns, indent))

    return lines


def _render_class(node: ast.ClassDef, indent: str = "") -> list[str]:
    if not _is_public(node.name):
        return []

    lines: list[str] = []

    for dec in node.decorator_list:
        rendered = _render_decorator(dec)
        if rendered:
            lines.append(f"{indent}{rendered}")

    bases = ", ".join(_unparse_safe(b) for b in node.bases)
    if bases:
        lines.append(f"{indent}class {node.name}({bases}):")
    else:
        lines.append(f"{indent}class {node.name}:")
    lines.append("")

    member_indent = indent + "    "
    member_blocks: list[list[str]] = []

    for child in node.body:
        match child:
            case ast.AnnAssign(target=ast.Name(id=name)) if _is_public(name, is_class_member=True):
                ann = _unparse_safe(child.annotation)
                if child.value is not None:
                    member_blocks.append([f"{member_indent}{name}: {ann} = ..."])
                else:
                    member_blocks.append([f"{member_indent}{name}: {ann}"])

            case ast.Assign(targets=[ast.Name(id=name)]) if _is_public(name, is_class_member=True) and name.isupper():
                if child.value is not None:
                    member_blocks.append([f"{member_indent}{name} = ..."])
                else:
                    member_blocks.append([f"{member_indent}{name}"])

            case ast.FunctionDef() | ast.AsyncFunctionDef():
                rendered = _render_function(child, member_indent, is_class_member=True)
                if rendered:
                    member_blocks.append(rendered)

            case ast.ClassDef() if _is_public(child.name):
                rendered = _render_class(child, member_indent)
                if rendered:
                    member_blocks.append(rendered)

    if not member_blocks:
        lines.append(f"{member_indent}...")
    else:
        for i, block in enumerate(member_blocks):
            if i > 0:
                lines.append("")
            lines.extend(block)

    return lines


def render_module_api(source: str, filename: str = "<unknown>") -> str:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        return f"# SyntaxError: {e.msg} (line {e.lineno})\n"

    lines: list[str] = []

    all_names: set[str] | None = None
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                        all_names = set()
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                all_names.add(elt.value)

    for node in ast.iter_child_nodes(tree):
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                name = node.name
                if all_names is not None and name not in all_names:
                    continue
                rendered = _render_function(node)
                if rendered:
                    if lines:
                        lines.append("")
                    lines.extend(rendered)

            case ast.ClassDef():
                name = node.name
                if all_names is not None and name not in all_names:
                    continue
                rendered = _render_class(node)
                if rendered:
                    if lines:
                        lines.append("")
                    lines.extend(rendered)

            case ast.AnnAssign(target=ast.Name(id=name)) if _is_public(name):
                if all_names is not None and name not in all_names:
                    continue
                ann = _unparse_safe(node.annotation)
                if node.value is not None:
                    line = f"{name}: {ann} = ..."
                else:
                    line = f"{name}: {ann}"
                if lines:
                    lines.append("")
                lines.append(line)

            case ast.Assign(targets=[ast.Name(id=name)]) if name.isupper() and _is_public(name):
                if all_names is not None and name not in all_names:
                    continue
                if node.value is not None:
                    line = f"{name} = ..."
                else:
                    line = f"{name}"
                if lines:
                    lines.append("")
                lines.append(line)

    if lines:
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# diffing
# ---------------------------------------------------------------------------

@dataclass
class FileDiff:
    path: str
    old_stub: str
    new_stub: str
    status: str


def _matches_any(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, f"*/{pattern}") or pattern in path:
            return True
    return False


def compute_file_diffs(base_ref: str, exclude: list[str] | None = None) -> list[FileDiff]:
    diffs: list[FileDiff] = []
    toplevel = git_toplevel()
    exclude = exclude or []

    for change in git_diff_files(base_ref):
        if _matches_any(change.path, exclude):
            logger.debug("excluded: %s", change.path)
            continue

        if change.status == "D":
            old_source = git_show(base_ref, change.path)
            old_stub = render_module_api(old_source, change.path) if old_source else ""
            if old_stub.strip():
                diffs.append(FileDiff(path=change.path, old_stub=old_stub, new_stub="", status="deleted"))
            continue

        old_ref_path = change.old_path if change.old_path else change.path
        old_source = git_show(base_ref, old_ref_path)

        abs_path = toplevel / change.path
        new_source = abs_path.read_text() if abs_path.exists() else None

        old_stub = render_module_api(old_source, old_ref_path) if old_source else ""
        new_stub = render_module_api(new_source, change.path) if new_source else ""

        if old_stub == new_stub:
            logger.debug("no API change: %s", change.path)
            continue

        if change.status == "R":
            status = "renamed"
            label = f"{change.old_path} -> {change.path}"
        elif change.status == "A":
            status = "added"
            label = change.path
        else:
            status = "modified"
            label = change.path

        diffs.append(FileDiff(path=label, old_stub=old_stub, new_stub=new_stub, status=status))

    diffs.sort(key=lambda d: d.path)
    return diffs


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

STATUS_LABEL = {
    "added": "+",
    "deleted": "-",
    "modified": "~",
    "renamed": ">",
}

STATUS_STYLE = {
    "added": "bold green",
    "deleted": "bold red",
    "modified": "bold yellow",
    "renamed": "bold blue",
}

MIN_HEADER_WIDTH = 80


def _split_into_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip() == "":
            if current:
                blocks.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _file_header(diff: FileDiff) -> tuple[str, str]:
    label = STATUS_LABEL.get(diff.status, "?")
    style = STATUS_STYLE.get(diff.status, "bold")
    inner = f" {label} {diff.path} "
    pad = max(MIN_HEADER_WIDTH - len(inner), 4)
    left = pad // 2
    right = pad - left
    return f"{'─' * left}{inner}{'─' * right}", style


def _block_name(block: str) -> str | None:
    for line in block.split("\n"):
        stripped = line.strip()
        if stripped.startswith("@"):
            continue
        if stripped.startswith("async def "):
            return stripped[10:].split("(")[0]
        if stripped.startswith("def "):
            return stripped[4:].split("(")[0]
        if stripped.startswith("class "):
            return stripped[6:].split("(")[0].rstrip(":")
        if ":" in stripped:
            return stripped.split(":")[0].strip()
        if "=" in stripped:
            return stripped.split("=")[0].strip()
        break
    return None


def _build_ops(old_blocks: list[str], new_blocks: list[str]) -> list[tuple]:
    ops: list[tuple] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_blocks, new_blocks).get_opcodes():
        if tag == "equal":
            for block in old_blocks[i1:i2]:
                ops.append(("equal", block))
        elif tag == "replace":
            old_by_name: dict[str, str] = {}
            for block in old_blocks[i1:i2]:
                name = _block_name(block)
                if name and name not in old_by_name:
                    old_by_name[name] = block

            paired: set[str] = set()
            for block in new_blocks[j1:j2]:
                name = _block_name(block)
                if name and name in old_by_name:
                    paired.add(name)

            for block in old_blocks[i1:i2]:
                name = _block_name(block)
                if name not in paired:
                    ops.append(("delete", block))

            for block in new_blocks[j1:j2]:
                name = _block_name(block)
                if name in paired:
                    ops.append(("modify", old_by_name[name], block))
                else:
                    ops.append(("insert", block))
        elif tag == "delete":
            for block in old_blocks[i1:i2]:
                ops.append(("delete", block))
        elif tag == "insert":
            for block in new_blocks[j1:j2]:
                ops.append(("insert", block))
    return ops


def _op_block(op: tuple) -> str:
    return op[2] if op[0] == "modify" else op[1]


def _print_modify(old_block: str, new_block: str, prefix_char: str, console: Console) -> None:
    old_lines = old_block.splitlines()
    new_lines = new_block.splitlines()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_lines, new_lines).get_opcodes():
        if tag == "equal":
            for line in old_lines[i1:i2]:
                console.print(f"{prefix_char}{escape(line)}", style="dim")
        else:
            for line in old_lines[i1:i2]:
                console.print(f"-{escape(line)}", style="red")
            for line in new_lines[j1:j2]:
                console.print(f"+{escape(line)}", style="green")


def print_diff(diff: FileDiff, console: Console, context: int = 1) -> None:
    header, style = _file_header(diff)
    console.print(f"\n{header}", style=style)

    old_blocks = _split_into_blocks(diff.old_stub)
    new_blocks = _split_into_blocks(diff.new_stub)
    ops = _build_ops(old_blocks, new_blocks)

    if not ops:
        return

    visible = [False] * len(ops)
    for i in range(len(ops)):
        if ops[i][0] != "equal":
            visible[i] = True
            for j in range(max(0, i - context), min(len(ops), i + context + 1)):
                if ops[j][0] == "equal":
                    ctx_block = _op_block(ops[j])
                    ctx_first = ctx_block.split("\n", 1)[0]
                    if ctx_first and ctx_first[0].isspace():
                        visible[j] = True

    for i in range(len(ops)):
        if not visible[i]:
            continue
        block = _op_block(ops[i])
        first_line = block.split("\n", 1)[0]
        if not first_line or not first_line[0].isspace():
            continue
        for j in range(i - 1, -1, -1):
            candidate = _op_block(ops[j])
            candidate_first = candidate.split("\n", 1)[0]
            if candidate_first and not candidate_first[0].isspace():
                visible[j] = True
                break

    last_was_hidden = False
    prev_tag = None
    for i, op in enumerate(ops):
        tag = op[0]
        if not visible[i]:
            if not last_was_hidden:
                gap_indent = ""
                for k in range(i, len(ops)):
                    if visible[k]:
                        break
                    hfirst = _op_block(ops[k]).split("\n", 1)[0]
                    if not hfirst or not hfirst[0].isspace():
                        break
                    if not gap_indent:
                        gap_indent = hfirst[: len(hfirst) - len(hfirst.lstrip())]
                if gap_indent:
                    console.print(f" {gap_indent}...", style="dim")
            last_was_hidden = True
            prev_tag = None
            continue

        last_was_hidden = False
        block = _op_block(op)
        first_line = block.split("\n", 1)[0]
        is_toplevel = first_line and not first_line[0].isspace()
        if prev_tag is not None and is_toplevel:
            if prev_tag != tag or tag != "equal":
                console.print()
        prev_tag = tag

        if tag == "modify":
            _print_modify(op[1], op[2], " ", console)
        else:
            prefix, block_style = {
                "equal":  (" ", "dim"),
                "delete": ("-", "red"),
                "insert": ("+", "green"),
            }[tag]
            for line in block.splitlines():
                console.print(f"{prefix}{escape(line)}", style=block_style)
    console.print()


def print_full(diff: FileDiff, console: Console) -> None:
    header, style = _file_header(diff)
    console.print(f"\n{header}", style=style)

    stub = diff.new_stub if diff.new_stub else diff.old_stub
    if not stub.strip():
        console.print("  (no public API)", style="dim")
        return

    for line in stub.splitlines():
        style = "green" if diff.status == "added" else "red" if diff.status == "deleted" else ""
        console.print(f"  {escape(line)}", style=style)


def run(
    base: str,
    mode: str,
    console: Console,
    exclude: list[str] | None = None,
) -> int:
    with stderr_console.status("Finding merge base..."):
        try:
            base_ref = git_merge_base(base)
        except subprocess.CalledProcessError:
            logger.error("could not find merge base with '%s'", base)
            return 1

    logger.debug("merge base: %s", base_ref)

    with stderr_console.status("Computing API diffs..."):
        diffs = compute_file_diffs(base_ref, exclude=exclude)

    if not diffs:
        console.print("No public API changes.", style="dim")
        return 0

    console.print(f"[bold]{len(diffs)} file(s) with API changes[/bold]\n")

    for diff in diffs:
        if mode == "diff":
            print_diff(diff, console)
        else:
            print_full(diff, console)

    console.print()
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Show public Python API surface changes between branches.",
        epilog="""
Environment variables:
  LOG_LEVEL        Logging level (default: WARNING)
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--base", default="main",
        help="Base branch to diff against (default: main)",
    )
    parser.add_argument(
        "--full", action="store_true",
        help="Show full API stubs instead of unified diff",
    )
    parser.add_argument(
        "--exclude", "-x", action="append", default=["test_*.py", "conftest.py"],
        help="Exclude files matching pattern (repeatable, default: test_*.py conftest.py)",
    )
    parser.add_argument(
        "--no-exclude", action="store_true",
        help="Disable default exclusions",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="Suppress all logging",
    )

    args = parser.parse_args(argv)

    level = logging.WARNING
    if args.verbose:
        level = logging.DEBUG
    elif args.quiet:
        level = logging.ERROR

    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=stderr_console, show_time=False, show_path=False)],
    )

    console = Console()
    mode = "full" if args.full else "diff"
    exclude = [] if args.no_exclude else args.exclude

    try:
        return run(args.base, mode, console, exclude=exclude)
    except subprocess.CalledProcessError as e:
        if args.verbose:
            logger.error("git command failed", exc_info=True)
        else:
            logger.error("git command failed: %s", e.cmd)
        return 1
    except Exception as e:
        if args.verbose:
            logger.error("unexpected error", exc_info=True)
        else:
            logger.error("error: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
