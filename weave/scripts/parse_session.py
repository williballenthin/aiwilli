#!/usr/bin/env python3
"""Parse agent session JSONL files (Claude Code or Pi Agent) and display
user messages, user-directed assistant messages, session metrics, and an
LLM-generated summary."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weave.app import (
    AGENT_SESSION_SUMMARY_PROMPT,
    SUMMARY_MODEL,
    SessionData,
    _format_duration,
    parse_session,
    render_session_turns,
)


def render_turns_plain(session: SessionData) -> str:
    parts: list[str] = []
    for i, turn in enumerate(session.turns, 1):
        ts = turn.timestamp.strftime("%H:%M:%S") if turn.timestamp else "??:??"
        parts.append(f"--- Turn {i} [{ts}] ---")
        parts.append(f"USER: {turn.user_text}")
        if turn.tool_names:
            parts.append(f"  [tools: {', '.join(turn.tool_names)}]")
        for text in turn.assistant_texts:
            parts.append(f"ASSISTANT: {text}")
        parts.append("")
    return "\n".join(parts)


def render_metrics(session: SessionData) -> str:
    info = session
    usage = session.usage
    lines: list[str] = []

    lines.append("=== Session Metrics ===")
    lines.append(f"Agent:       {info.agent}")
    lines.append(f"Session ID:  {info.session_id}")
    lines.append(f"Project:     {info.project}")
    lines.append(f"Directory:   {info.cwd}")
    if info.git_branch:
        lines.append(f"Git branch:  {info.git_branch}")
    if info.models:
        lines.append(f"Model(s):    {', '.join(info.models)}")
    if info.start_time:
        lines.append(f"Started:     {info.start_time.isoformat()}")
    if info.end_time:
        lines.append(f"Ended:       {info.end_time.isoformat()}")
    if info.duration:
        lines.append(f"Duration:    {_format_duration(info.duration)}")

    lines.append("")
    lines.append("--- Tokens ---")
    lines.append(f"Input:       {usage.input_tokens:,}")
    lines.append(f"Output:      {usage.output_tokens:,}")
    lines.append(f"Cache read:  {usage.cache_read_tokens:,}")
    lines.append(f"Cache write: {usage.cache_write_tokens:,}")
    total = usage.input_tokens + usage.output_tokens + usage.cache_read_tokens + usage.cache_write_tokens
    lines.append(f"Total:       {total:,}")
    if usage.cost is not None:
        lines.append(f"Cost:        ${usage.cost:.4f}")

    lines.append("")
    lines.append("--- Messages ---")
    lines.append(f"User turns:       {len(session.turns)}")
    assistant_count = sum(len(t.assistant_texts) for t in session.turns)
    lines.append(f"Assistant texts:  {assistant_count}")
    lines.append(f"Tool calls:       {session.total_tool_calls}")
    lines.append(f"Thinking blocks:  {session.total_thinking_blocks}")

    return "\n".join(lines)


def build_summary_input(session: SessionData) -> str:
    parts: list[str] = []
    parts.append(f"Agent: {session.agent}")
    parts.append(f"Project: {session.project}")
    if session.duration:
        parts.append(f"Duration: {_format_duration(session.duration)}")
    parts.append(f"Tool calls: {session.total_tool_calls}")
    parts.append("")
    parts.append(render_turns_plain(session))
    return "\n".join(parts)


def summarize(session: SessionData, model: str) -> str:
    input_text = build_summary_input(session)
    try:
        result = subprocess.run(
            ["llm", "-m", model, AGENT_SESSION_SUMMARY_PROMPT],
            input=input_text,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"error: llm failed: {exc.stderr}", file=sys.stderr)
        return ""
    except FileNotFoundError:
        print("error: llm command not found", file=sys.stderr)
        return ""
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse agent session JSONL files")
    parser.add_argument("session_file", type=Path, help="Path to .jsonl session file")
    parser.add_argument("--no-summary", action="store_true", help="Skip LLM summary")
    parser.add_argument("--model", default=SUMMARY_MODEL, help=f"LLM model for summary (default: {SUMMARY_MODEL})")
    parser.add_argument("--metrics-only", action="store_true", help="Only show metrics, no conversation")
    args = parser.parse_args()

    path: Path = args.session_file
    if not path.exists():
        print(f"error: {path} not found", file=sys.stderr)
        sys.exit(1)

    session = parse_session(path)

    if not args.metrics_only:
        print(render_turns_plain(session))

    print(render_metrics(session))

    if not args.no_summary and session.turns:
        print("\n=== LLM Summary ===")
        summary = summarize(session, args.model)
        if summary:
            print(summary)
        else:
            print("(summary unavailable)")


if __name__ == "__main__":
    main()
