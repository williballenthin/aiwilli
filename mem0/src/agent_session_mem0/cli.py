from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import click
import httpx
from mem0 import Memory
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

logger = logging.getLogger(__name__)
stderr_console = Console(stderr=True)

DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "agent-session-mem0"

TURN_EXTRACTION_PROMPT = """\
You are analyzing transcripts from AI coding assistant sessions. Extract durable knowledge \
about the user — things worth remembering for future sessions.

## What to extract (primary — always capture these)

- **Preferences & opinions**: tools, languages, coding style, what the user likes/dislikes and WHY
- **Corrections & rejections**: things the user told the assistant NOT to do, and why
- **Skills & expertise**: demonstrated technical knowledge, domains of competence, experience level
- **Beliefs & mental models**: how the user thinks about problems, engineering philosophy
- **Relationships**: people, companies, projects, and tools — how they relate to the user
- **Personal context**: role, team, company, location

## What to extract (secondary — capture when durable)

- **Projects**: the project itself and its purpose, NOT today's specific task on it
- **Workflows**: how the user works, automation, development flow
- **Technical decisions**: architecture/design/library choices WITH the reasoning behind them

## What NOT to extract

- Specific code changes, file edits, refactoring steps (git history has these)
- File paths, function names, variable names (stale quickly)
- Current task progress or what the assistant is doing right now
- Generic pleasantries, meta-conversation, or facts about the AI assistant

## Rules

- Include reasoning when the conversation reveals it. \
"User chose Click over argparse because the tool needs many subcommands" not just "User uses Click"
- Each observation should be a single, self-contained statement that would make sense to \
someone with no context
- Use the preceding messages to enrich observations from the current turn. If the reason for \
a decision or preference appeared in an earlier message, incorporate it
- Prefer fewer, richer observations over many shallow ones

## Examples

Input: "Don't mock the database in these tests — we got burned last quarter."
Good: {"facts": ["User rejects database mocks because mock/prod divergence hid a broken migration"]}
Bad: {"facts": ["User doesn't use mocks", "There was a production failure"]}

Input: "I work at Hex-Rays. Can you fix this IDAPython script?"
Good: {"facts": ["User works at Hex-Rays (IDA Pro company)", "User develops IDAPython scripts"]}

Input: "I use Helix as my editor with Zellij for terminal multiplexing on macOS."
Good: {"facts": ["User's primary editor is Helix with Zellij for terminal multiplexing on macOS"]}

Input: "no, don't use a class-based test — just use plain functions with pytest"
Good: {"facts": ["User prefers free-function pytest style over class-based tests"]}

Input: "Let me just push that fix real quick... ok done. Now let's work on the API endpoint."
Good: {"facts": []}

Return ONLY a JSON object with a "facts" key containing an array of strings.
"""

SESSION_DISTILLATION_PROMPT = """\
You are reviewing observations extracted from one AI coding assistant session. Your job is to \
identify the most important things to remember about this user for future sessions.

You will receive:
1. Observations extracted from individual turns in the current session
2. (Optionally) Prior knowledge about this user from previous sessions

## Produce insights that are:

- **Durable**: still true and useful weeks or months from now
- **User-level**: about the person — their preferences, expertise, \
reasoning, relationships — not about a specific task
- **Synthesized**: combine multiple observations into higher-order \
patterns when possible. If 5 observations mention IDA Pro, the insight \
is "User develops IDA Pro plugins professionally", not 5 separate facts
- **Enriched by prior knowledge**: if prior memories reinforce or \
contradict current observations, note that. "User consistently prefers \
X" is more valuable than "User prefers X" across sessions

## Do NOT produce:

- Implementation details: file changes, specific bugs fixed, refactoring steps
- Restatements of single observations without added synthesis
- Facts about the AI assistant or the conversation mechanics
- Anything already fully captured in a single observation (don't just rephrase it)

Return ONLY a JSON object: {"insights": ["insight 1", "insight 2", ...]}
If the observations contain no durable user-level knowledge, return {"insights": []}.
"""

MAX_USER_CONTEXT_TURNS = 16
ASSISTANT_CONTEXT_TURNS = 4


def _build_config(data_dir: Path | None = None) -> dict[str, Any]:
    faiss_path = str((data_dir or DEFAULT_DATA_DIR) / "faiss")
    return {
        "llm": {
            "provider": "lmstudio",
            "config": {
                "model": LMSTUDIO_MODEL,
                "max_tokens": 4000,
                "lmstudio_base_url": LMSTUDIO_BASE_URL,
                "lmstudio_response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "response",
                        "strict": True,
                        "schema": {"type": "object", "additionalProperties": True},
                    },
                },
            },
        },
        "embedder": {
            "provider": "lmstudio",
            "config": {
                "model": "text-embedding-nomic-embed-text-v1.5",
            },
        },
        "vector_store": {
            "provider": "faiss",
            "config": {
                "collection_name": "sessions",
                "path": faiss_path,
                "embedding_model_dims": 768,
                "distance_strategy": "cosine",
            },
        },
        "custom_fact_extraction_prompt": TURN_EXTRACTION_PROMPT,
        "version": "v1.1",
    }


LMSTUDIO_BASE_URL = "http://localhost:1234/v1"
LMSTUDIO_MODEL = "gemma-4-26b-a4b-it"


def _call_lmstudio(system_prompt: str, user_content: str) -> dict[str, Any]:
    """Call lmstudio chat completions directly, bypassing mem0.

    Returns the parsed JSON from the assistant's response content.
    """
    resp = httpx.post(
        f"{LMSTUDIO_BASE_URL}/chat/completions",
        json={
            "model": LMSTUDIO_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": 4000,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": {"type": "object", "additionalProperties": True},
                },
            },
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    content: str = resp.json()["choices"][0]["message"]["content"]
    result: dict[str, Any] = json.loads(content)
    return result


# --- Indexing manifest ---


def _manifest_db(config: dict[str, Any]) -> Path:
    faiss_path = config["vector_store"]["config"]["path"]
    return Path(faiss_path).parent / "manifest.db"


def _init_manifest(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS indexed_files ("
        "  content_hash TEXT PRIMARY KEY,"
        "  path TEXT NOT NULL,"
        "  session_id TEXT NOT NULL,"
        "  turns INTEGER NOT NULL,"
        "  indexed_at TEXT NOT NULL"
        ")"
    )
    conn.commit()
    return conn


def _file_content_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_already_indexed(conn: sqlite3.Connection, content_hash: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT path, session_id, turns, indexed_at FROM indexed_files WHERE content_hash = ?",
        (content_hash,),
    ).fetchone()
    if row is None:
        return None
    return {"path": row[0], "session_id": row[1], "turns": row[2], "indexed_at": row[3]}


def _record_indexed(
    conn: sqlite3.Connection,
    content_hash: str,
    path: Path,
    session_id: str,
    turns: int,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO indexed_files (content_hash, path, session_id, turns, indexed_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            content_hash,
            str(path.resolve()),
            session_id,
            turns,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


# --- Rendering helpers ---


def _parse_mem0_timestamp(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str)


def _time_bucket(dt: datetime, now: datetime) -> str:
    delta = now - dt
    if delta < timedelta(hours=1):
        return "Last hour"
    if delta < timedelta(days=1):
        return "Today"
    if delta < timedelta(days=2):
        return "Yesterday"
    if delta < timedelta(days=7):
        return "This week"
    if delta < timedelta(days=30):
        return "This month"
    months = int(delta.days / 30)
    if months <= 1:
        return "1 month ago"
    return f"{months} months ago"


def _short_session(session_id: str) -> str:
    return session_id[:8] if len(session_id) > 8 else session_id


def _render_fact_row(entry: dict[str, Any]) -> dict[str, Any]:
    meta = entry.get("metadata") or {}
    ts_str = meta.get("timestamp") or entry.get("created_at", "")
    ts = _parse_mem0_timestamp(ts_str) if ts_str else None
    return {
        "timestamp": ts.strftime("%Y-%m-%d %H:%M") if ts else "",
        "agent": meta.get("agent", ""),
        "project": meta.get("project", ""),
        "session": _short_session(meta.get("session_id", "")),
        "memory": entry.get("memory", ""),
        "score": entry.get("score"),
        "dt": ts,
    }


def _print_timeline(console: Console, entries: list[dict[str, Any]], now: datetime) -> None:
    rows = [_render_fact_row(e) for e in entries]
    rows.sort(key=lambda r: r["dt"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        bucket = _time_bucket(row["dt"], now) if row["dt"] else "Unknown"
        buckets[bucket].append(row)

    bucket_order = [
        "Last hour",
        "Today",
        "Yesterday",
        "This week",
        "This month",
    ]
    seen = set()
    ordered_keys = []
    for b in bucket_order:
        if b in buckets:
            ordered_keys.append(b)
            seen.add(b)
    for b in buckets:
        if b not in seen:
            ordered_keys.append(b)

    for bucket_name in ordered_keys:
        bucket_rows = buckets[bucket_name]
        console.print()
        console.print(f"[bold]{bucket_name}[/bold] ({len(bucket_rows)})")

        table = Table(show_header=True, pad_edge=False, box=None)
        table.add_column("Time", style="dim", width=16)
        table.add_column("Project", style="cyan", width=14)
        table.add_column("Session", style="dim", width=10)
        table.add_column("Fact", style="white")

        for row in bucket_rows:
            table.add_row(row["timestamp"], row["project"], row["session"], row["memory"])

        console.print(table)


def _print_ranked(console: Console, entries: list[dict[str, Any]]) -> None:
    table = Table(show_header=True, title="Top results")
    table.add_column("Score", style="cyan", width=8)
    table.add_column("Time", style="dim", width=16)
    table.add_column("Project", style="cyan", width=14)
    table.add_column("Fact", style="white")

    for entry in entries:
        row = _render_fact_row(entry)
        score = f"{row['score']:.3f}" if row["score"] is not None else ""
        table.add_row(score, row["timestamp"], row["project"], row["memory"])

    console.print(table)


# --- Session parsing (adapted from weave) ---


@dataclass
class SessionTurn:
    user_text: str
    assistant_texts: list[str]
    tool_names: list[str]
    timestamp: datetime | None = None


@dataclass
class SessionData:
    agent: str
    session_id: str
    project: str
    turns: list[SessionTurn] = field(default_factory=list)


def _parse_timestamp(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def detect_session_format(path: Path) -> str:
    with open(path) as f:
        first_line = f.readline()
    obj = json.loads(first_line)
    if obj.get("type") == "session" and "version" in obj:
        return "pi"
    return "claude"


def _is_human_user_msg(obj: dict[str, Any]) -> bool:
    if obj.get("type") != "user":
        return False
    if obj.get("isMeta"):
        return False
    content = obj.get("message", {}).get("content", "")
    if isinstance(content, list):
        return False
    if isinstance(content, str):
        if content.startswith(("<bash-", "<local-command", "<task-notification")):
            return False
        return True
    return False


def _build_claude_turns(messages: list[dict[str, Any]]) -> list[SessionTurn]:
    turns: list[SessionTurn] = []
    current_user_text: str | None = None
    current_user_ts: datetime | None = None
    current_assistant_texts: list[str] = []
    current_tool_names: list[str] = []

    for obj in messages:
        if _is_human_user_msg(obj):
            if current_user_text is not None:
                turns.append(
                    SessionTurn(
                        user_text=current_user_text,
                        assistant_texts=current_assistant_texts,
                        tool_names=current_tool_names,
                        timestamp=current_user_ts,
                    )
                )
            current_user_text = obj.get("message", {}).get("content", "")
            ts_str = obj.get("timestamp")
            current_user_ts = _parse_timestamp(ts_str) if ts_str else None
            current_assistant_texts = []
            current_tool_names = []
        elif obj.get("type") == "assistant" and current_user_text is not None:
            for block in obj.get("message", {}).get("content", []):
                bt = block.get("type")
                if bt == "text":
                    text = block.get("text", "").strip()
                    if text and text != "No response requested.":
                        current_assistant_texts.append(text)
                elif bt == "tool_use":
                    current_tool_names.append(block.get("name", "unknown"))

    if current_user_text is not None:
        turns.append(
            SessionTurn(
                user_text=current_user_text,
                assistant_texts=current_assistant_texts,
                tool_names=current_tool_names,
                timestamp=current_user_ts,
            )
        )
    return turns


def _build_pi_turns(messages: list[dict[str, Any]]) -> list[SessionTurn]:
    turns: list[SessionTurn] = []
    current_user_text: str | None = None
    current_user_ts: datetime | None = None
    current_assistant_texts: list[str] = []
    current_tool_names: list[str] = []

    for obj in messages:
        msg = obj.get("message", {})
        role = msg.get("role")
        if role == "user":
            if current_user_text is not None:
                turns.append(
                    SessionTurn(
                        user_text=current_user_text,
                        assistant_texts=current_assistant_texts,
                        tool_names=current_tool_names,
                        timestamp=current_user_ts,
                    )
                )
            text_parts = []
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block["text"])
            current_user_text = "\n".join(text_parts)
            ts_str = obj.get("timestamp")
            current_user_ts = _parse_timestamp(ts_str) if ts_str else None
            current_assistant_texts = []
            current_tool_names = []
        elif role == "assistant" and current_user_text is not None:
            for block in msg.get("content", []):
                if isinstance(block, dict):
                    bt = block.get("type")
                    if bt == "text":
                        text = block.get("text", "").strip()
                        if text:
                            current_assistant_texts.append(text)
                    elif bt == "toolCall":
                        current_tool_names.append(block.get("name", "unknown"))

    if current_user_text is not None:
        turns.append(
            SessionTurn(
                user_text=current_user_text,
                assistant_texts=current_assistant_texts,
                tool_names=current_tool_names,
                timestamp=current_user_ts,
            )
        )
    return turns


def _extract_project(messages: list[dict[str, Any]], fmt: str) -> str:
    """Derive project name from the session's cwd."""
    for obj in messages:
        cwd = obj.get("cwd")
        if cwd:
            return Path(cwd).name
    return ""


def _get_session_id(path: Path, fmt: str) -> str:
    with open(path) as f:
        first_line = f.readline()
    obj = json.loads(first_line)
    if fmt == "pi":
        return str(obj.get("id", path.stem))
    return str(obj.get("sessionId", path.stem))


def parse_session(path: Path) -> SessionData:
    fmt = detect_session_format(path)
    session_id = _get_session_id(path, fmt)

    messages = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                messages.append(json.loads(line))

    project = _extract_project(messages, fmt)

    if fmt == "pi":
        msg_entries = [m for m in messages if m.get("type") == "message"]
        turns = _build_pi_turns(msg_entries)
    else:
        turns = _build_claude_turns(messages)

    return SessionData(agent=fmt, session_id=session_id, project=project, turns=turns)


# --- Markdown (weave/obsidian) session parsing ---

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_CALLOUT_RE = re.compile(r"> \[!(\w+)\] (.+)")
_METRICS_ROW_RE = re.compile(r"\| (.+?) \| (.+?) \|")
_SUMMARY_RE = re.compile(
    r"<!-- weave:summary:start -->\n(.*?)\n<!-- weave:summary:end -->",
    re.DOTALL,
)


def _parse_yaml_frontmatter(text: str) -> dict[str, str]:
    """Minimal YAML frontmatter parser (no pyyaml dependency)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    result: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip().strip('"')
        result[key.strip()] = val
    return result


def _parse_metrics_table(text: str) -> dict[str, str]:
    metrics: dict[str, str] = {}
    in_table = False
    for line in text.splitlines():
        if line.startswith("| Metric"):
            in_table = True
            continue
        if line.startswith("|---"):
            continue
        if in_table:
            m = _METRICS_ROW_RE.match(line)
            if m:
                metrics[m.group(1).strip()] = m.group(2).strip()
            else:
                in_table = False
    return metrics


def _parse_md_conversation(text: str) -> list[SessionTurn]:
    """Parse Obsidian callout blocks into SessionTurns."""
    turns: list[SessionTurn] = []
    current_user_text: str | None = None
    current_user_ts: datetime | None = None
    current_assistant_texts: list[str] = []
    current_tool_names: list[str] = []

    conv_start = text.find("## Conversation")
    if conv_start == -1:
        return []
    conv_text = text[conv_start:]

    collecting: str | None = None  # "user" or "assistant"
    buf_lines: list[str] = []

    def _flush_assistant() -> None:
        nonlocal current_tool_names
        body = "\n".join(buf_lines).strip()
        if not body:
            return
        first_line = body.split("\n", 1)[0]
        if first_line.startswith("tools:"):
            current_tool_names = [t.strip() for t in first_line[6:].split(",")]
            body = body[len(first_line) :].strip()
        if body:
            current_assistant_texts.append(body)

    for line in conv_text.splitlines():
        m = _CALLOUT_RE.match(line)
        if m:
            callout_type = m.group(1)
            title = m.group(2)

            if collecting == "assistant":
                _flush_assistant()
                buf_lines = []

            if callout_type == "note" and title.startswith("User"):
                if current_user_text is not None:
                    turns.append(
                        SessionTurn(
                            user_text=current_user_text,
                            assistant_texts=current_assistant_texts,
                            tool_names=current_tool_names,
                            timestamp=current_user_ts,
                        )
                    )
                current_assistant_texts = []
                current_tool_names = []
                ts_match = re.search(r"(\d{2}:\d{2}:\d{2})", title)
                current_user_ts = None
                if ts_match:
                    current_user_ts_str = ts_match.group(1)
                    # Will be combined with date from metrics later
                    current_user_ts = datetime.strptime(current_user_ts_str, "%H:%M:%S").replace(
                        tzinfo=timezone.utc
                    )
                current_user_text = ""
                collecting = "user"
                buf_lines = []

            elif callout_type == "quote" and "Assistant" in title:
                if collecting == "user":
                    current_user_text = "\n".join(buf_lines).strip()
                collecting = "assistant"
                buf_lines = []
            continue

        if line.startswith("> "):
            buf_lines.append(line[2:])
        elif line == ">":
            buf_lines.append("")

    if collecting == "assistant":
        _flush_assistant()
    if collecting == "user":
        current_user_text = "\n".join(buf_lines).strip()

    if current_user_text is not None:
        turns.append(
            SessionTurn(
                user_text=current_user_text,
                assistant_texts=current_assistant_texts,
                tool_names=current_tool_names,
                timestamp=current_user_ts,
            )
        )

    return turns


def parse_md_session(path: Path) -> SessionData:
    text = path.read_text()
    fm = _parse_yaml_frontmatter(text)
    metrics = _parse_metrics_table(text)

    agent = fm.get("agent", "")
    session_id = fm.get("session_id", path.stem)
    project = fm.get("project", "")

    turns = _parse_md_conversation(text)

    started = metrics.get("Started", "")
    if started:
        try:
            session_date = datetime.fromisoformat(started)
            for turn in turns:
                if turn.timestamp and turn.timestamp.year == 1900:
                    turn.timestamp = turn.timestamp.replace(
                        year=session_date.year,
                        month=session_date.month,
                        day=session_date.day,
                    )
        except ValueError:
            pass

    summary_match = _SUMMARY_RE.search(text)
    if summary_match:
        summary_text = summary_match.group(1).strip()
        if summary_text:
            summary_turn = SessionTurn(
                user_text="Session summary follows.",
                assistant_texts=[summary_text],
                tool_names=[],
                timestamp=turns[0].timestamp if turns else None,
            )
            turns.insert(0, summary_turn)

    return SessionData(agent=agent, session_id=session_id, project=project, turns=turns)


def _detect_file_format(path: Path) -> str:
    if path.suffix == ".md":
        return "md"
    return "jsonl"


def _turn_to_messages(turn: SessionTurn) -> list[dict[str, str]]:
    """Convert a single turn into [user_msg] or [user_msg, assistant_msg]."""
    msgs: list[dict[str, str]] = [{"role": "user", "content": turn.user_text}]
    if turn.assistant_texts:
        msgs.append({"role": "assistant", "content": "\n\n".join(turn.assistant_texts)})
    return msgs


def build_contextual_messages(
    turns: list[SessionTurn],
    target_idx: int,
    max_user_context: int = MAX_USER_CONTEXT_TURNS,
    assistant_context: int = ASSISTANT_CONTEXT_TURNS,
) -> list[dict[str, str]]:
    """Build a message list with preceding context plus the target turn.

    Includes up to `max_user_context` prior user messages for topic continuity,
    and includes assistant responses only for the `assistant_context` most recent
    prior turns (since assistant text is bulky and only nearby context matters).
    The target turn always includes both user and assistant text.
    """
    start = max(0, target_idx - max_user_context)
    assistant_cutoff = target_idx - assistant_context

    messages: list[dict[str, str]] = []
    for i in range(start, target_idx):
        turn = turns[i]
        if not turn.user_text.strip():
            continue
        messages.append({"role": "user", "content": turn.user_text})
        if i >= assistant_cutoff and turn.assistant_texts:
            messages.append({"role": "assistant", "content": "\n\n".join(turn.assistant_texts)})

    messages.extend(_turn_to_messages(turns[target_idx]))
    return messages


# --- Session distillation (pass 2) ---

CROSS_SESSION_QUERY_LIMIT = 20


def _retrieve_session_context(
    m: Memory,
    user_id: str,
    session: SessionData,
) -> list[str]:
    """Query existing store for memories related to this session."""
    queries: list[str] = []
    if session.project:
        queries.append(session.project)
    for turn in session.turns[:5]:
        text = turn.user_text.strip()
        if text:
            queries.append(text[:200])
        if len(queries) >= 4:
            break

    seen: set[str] = set()
    results: list[str] = []
    for q in queries:
        try:
            hits = m.search(q, user_id=user_id, limit=CROSS_SESSION_QUERY_LIMIT)
        except Exception:
            logger.debug("Cross-session query failed for %r", q[:50], exc_info=True)
            continue
        for entry in hits.get("results", []):
            mem = entry.get("memory", "")
            if mem and mem not in seen:
                seen.add(mem)
                results.append(mem)
    return results


def _distill_session(
    observations: list[str],
    prior_context: list[str],
) -> list[str]:
    """Run session distillation via direct LLM call.

    Returns a list of distilled insight strings.
    """
    parts: list[str] = []
    if prior_context:
        parts.append("## Prior knowledge about this user\n")
        for mem in prior_context:
            parts.append(f"- {mem}")
        parts.append("")
    parts.append("## Observations from this session\n")
    for obs in observations:
        parts.append(f"- {obs}")

    user_content = "\n".join(parts)
    result = _call_lmstudio(SESSION_DISTILLATION_PROMPT, user_content)
    insights: list[str] = result.get("insights", [])
    return insights


# --- Ingestion engine ---


@dataclass
class IngestionResult:
    status: str
    session_id: str
    project: str
    agent: str
    turns: int
    observations: int
    insights: int


def _ingest_file(
    path: Path,
    config: dict[str, Any],
    user_id: str,
    force: bool,
    m: Memory,
    conn: sqlite3.Connection,
    progress: Progress,
    detail_task: TaskID,
) -> IngestionResult:
    content_hash = _file_content_hash(path)

    if not force:
        prior = _is_already_indexed(conn, content_hash)
        if prior:
            return IngestionResult(
                "skipped", prior["session_id"], "", "", prior["turns"], 0, 0,
            )

    fmt = _detect_file_format(path)
    if fmt == "md":
        session = parse_md_session(path)
    else:
        session = parse_session(path)

    non_empty_indices = [i for i, t in enumerate(session.turns) if t.user_text.strip()]
    if not non_empty_indices:
        return IngestionResult(
            "empty", session.session_id, session.project, session.agent, 0, 0, 0,
        )

    logger.debug(
        "Parsed %s session %s (%s): %d turns (%d non-empty)",
        session.agent,
        session.session_id,
        session.project,
        len(session.turns),
        len(non_empty_indices),
    )

    sid = _short_session(session.session_id)
    collected_observations: list[str] = []
    msg_count = 0

    n_turns = len(non_empty_indices)
    progress.reset(detail_task, total=n_turns, completed=0,
                   description=f"[bold]pass 1[/bold] [dim]{sid}[/dim]")
    progress.update(detail_task, counts=_fmt_counts(0, n_turns),
                    info="0 msgs · 0 memories", visible=True)

    for step, idx in enumerate(non_empty_indices, 1):
        turn = session.turns[idx]
        metadata = {
            "agent": session.agent,
            "session_id": session.session_id,
            "project": session.project,
            "timestamp": turn.timestamp.isoformat() if turn.timestamp else "",
            "memory_type": "observation",
        }
        messages = build_contextual_messages(session.turns, idx)
        result = m.add(messages, user_id=user_id, metadata=metadata)
        msg_count += len(messages)
        logger.debug("Turn %d result: %s", idx + 1, result)
        for entry in result.get("results", []):
            if entry.get("event") == "ADD" and entry.get("memory"):
                collected_observations.append(entry["memory"])
                progress.console.print(f"  [blue]observation:[/blue] {entry['memory']}")
        progress.update(detail_task, advance=1,
                       counts=_fmt_counts(step, n_turns),
                       info=f"{msg_count} msgs · {len(collected_observations)} memories")

    mem_count = len(collected_observations)
    progress.reset(detail_task, completed=0,
                   description=f"[bold]pass 2[/bold] [dim]{sid}[/dim]")
    progress.update(detail_task, counts="", info=f"retrieving context · {mem_count} memories")

    prior_context = _retrieve_session_context(m, user_id, session)
    logger.debug("Cross-session context: %d prior memories", len(prior_context))

    progress.update(detail_task, info=f"distilling · {mem_count} memories")
    insights = _distill_session(collected_observations, prior_context)

    progress.update(detail_task, info=f"storing insights · {mem_count} memories")
    insight_metadata = {
        "agent": session.agent,
        "session_id": session.session_id,
        "project": session.project,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "memory_type": "insight",
    }
    for insight in insights:
        m.add(
            [{"role": "user", "content": insight}],
            user_id=user_id, metadata=insight_metadata, infer=False,
        )
        mem_count += 1
        progress.update(detail_task, info=f"storing insights · {mem_count} memories")
        progress.console.print(f"  [green]insight:[/green] {insight}")

    _record_indexed(conn, content_hash, path, session.session_id, len(non_empty_indices))

    return IngestionResult(
        "ingested", session.session_id, session.project, session.agent,
        len(non_empty_indices), len(collected_observations), len(insights),
    )


def _fmt_counts(completed: int, total: int) -> str:
    w = len(str(total))
    return f"{completed:>{w}}/{total}"


def _make_progress(transient: bool = True) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TextColumn("[green]{task.fields[counts]:>9}[/green]"),
        TextColumn("{task.fields[info]}"),
        TextColumn("[dim]·[/dim]"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=stderr_console,
        transient=transient,
    )


# --- CLI ---


@click.group()
@click.option("--verbose", is_flag=True, help="Enable debug logging.")
@click.option("--quiet", is_flag=True, help="Suppress logging.")
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Override data directory for FAISS store.",
)
@click.pass_context
def cli(ctx: click.Context, verbose: bool, quiet: bool, data_dir: Path | None) -> None:
    level = logging.DEBUG if verbose else logging.ERROR if quiet else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )
    for noisy in ("httpx", "mem0", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    ctx.ensure_object(dict)
    ctx.obj["config"] = _build_config(data_dir)


@cli.command("add-session")
@click.argument("session_path", type=click.Path(exists=True, path_type=Path))
@click.option("--user-id", default="willi", show_default=True)
@click.option("--force", is_flag=True, help="Re-index even if already indexed.")
@click.pass_context
def add_session(ctx: click.Context, session_path: Path, user_id: str, force: bool) -> None:
    """Ingest a session file (.jsonl or weave .md) into mem0."""
    config = ctx.obj["config"]
    conn = _init_manifest(_manifest_db(config))

    with stderr_console.status("Loading mem0..."):
        m = Memory.from_config(config)

    with _make_progress() as progress:
        detail_task = progress.add_task("starting", total=0, counts="", info="")
        result = _ingest_file(session_path, config, user_id, force, m, conn, progress, detail_task)

    conn.close()

    if result.status == "skipped":
        stderr_console.print(
            f"[dim]Skipped {session_path.name} — already indexed ({result.turns} turns)[/dim]"
        )
        return

    if result.status == "empty":
        stderr_console.print("[yellow]No conversation turns found.[/yellow]")
        return

    stderr_console.print(
        f"Added {result.turns} turns ({result.observations} observations, "
        f"{result.insights} insights) from {result.agent} session "
        f"{result.session_id} ({result.project})"
    )


@cli.command("add-dir")
@click.argument("directory", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--user-id", default="willi", show_default=True)
@click.option("--force", is_flag=True, help="Re-index even if already indexed.")
@click.option(
    "--glob", "file_glob",
    default="**/agent sessions/*.md",
    show_default=True,
    help="Glob pattern for finding session files.",
)
@click.pass_context
def add_dir(ctx: click.Context, directory: Path, user_id: str, force: bool, file_glob: str) -> None:
    """Ingest all session files under a directory."""
    config = ctx.obj["config"]

    files = sorted(directory.glob(file_glob))
    if not files:
        stderr_console.print(f"[yellow]No files matching {file_glob!r} in {directory}[/yellow]")
        return

    stderr_console.print(f"Found {len(files)} session files")

    conn = _init_manifest(_manifest_db(config))
    with stderr_console.status("Loading mem0..."):
        m = Memory.from_config(config)

    ingested = 0
    skipped = 0
    failed = 0

    n_files = len(files)
    with _make_progress(transient=False) as progress:
        files_task = progress.add_task(
            "[bold]files[/bold]", total=n_files,
            counts=_fmt_counts(0, n_files),
            info="0 ingested · 0 skipped · 0 failed",
        )
        detail_task = progress.add_task("waiting", total=0, counts="", info="", visible=False)

        for session_path in files:
            try:
                progress.update(detail_task, visible=True)
                result = _ingest_file(
                    session_path, config, user_id, force, m, conn, progress, detail_task,
                )
                if result.status in ("skipped", "empty"):
                    skipped += 1
                    progress.console.print(f"  [dim]skipped {session_path.name}[/dim]")
                else:
                    ingested += 1
                    progress.console.print(
                        f"  [dim]ingested {session_path.name}: "
                        f"{result.observations} obs, {result.insights} insights[/dim]"
                    )
            except Exception as e:
                failed += 1
                progress.console.print(f"  [red]failed {session_path.name}: {e}[/red]")
                logger.debug("Failed to process %s", session_path, exc_info=True)

            file_step = ingested + skipped + failed
            progress.update(detail_task, visible=False)
            progress.update(
                files_task, advance=1,
                counts=_fmt_counts(file_step, n_files),
                info=f"{ingested} ingested · {skipped} skipped · {failed} failed",
            )

    conn.close()
    stderr_console.print(
        f"\nDone: {ingested} ingested, {skipped} skipped, {failed} failed"
    )


@cli.command("query")
@click.argument("query_text")
@click.option("--user-id", default="willi", show_default=True)
@click.option("--limit", "-n", default=10, show_default=True)
@click.pass_context
def query(ctx: click.Context, query_text: str, user_id: str, limit: int) -> None:
    """Search mem0 memories. Shows ranked results and a timeline view."""
    with stderr_console.status("Loading mem0..."):
        m = Memory.from_config(ctx.obj["config"])

    with stderr_console.status("Searching..."):
        results = m.search(query_text, user_id=user_id, limit=limit)

    entries = results.get("results", [])
    if not entries:
        click.echo("No results found.")
        return

    console = Console()
    now = datetime.now(timezone.utc)

    _print_ranked(console, entries)
    console.print()
    console.rule("[dim]Timeline[/dim]")
    _print_timeline(console, entries, now)
    console.print()


@cli.command("list")
@click.option("--user-id", default="willi", show_default=True)
@click.pass_context
def list_facts(ctx: click.Context, user_id: str) -> None:
    """Show all stored facts grouped by time period."""
    with stderr_console.status("Loading mem0..."):
        m = Memory.from_config(ctx.obj["config"])

    with stderr_console.status("Fetching all memories..."):
        all_mems = m.get_all(user_id=user_id)

    entries = all_mems.get("results", [])
    if not entries:
        click.echo("No facts stored.")
        return

    console = Console()
    now = datetime.now(timezone.utc)

    console.print(f"[bold]{len(entries)}[/bold] facts stored\n")
    _print_timeline(console, entries, now)
    console.print()


@cli.command("reset")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def reset(ctx: click.Context, yes: bool) -> None:
    """Delete all memories and reset the FAISS index."""
    config = ctx.obj["config"]
    faiss_dir = Path(config["vector_store"]["config"]["path"])

    if not yes:
        click.confirm(f"Delete all data in {faiss_dir}?", abort=True)

    with stderr_console.status("Resetting..."):
        m = Memory.from_config(config)
        m.reset()

    if faiss_dir.exists():
        shutil.rmtree(faiss_dir)

    manifest = _manifest_db(config)
    if manifest.exists():
        manifest.unlink()

    stderr_console.print("Index reset.")


if __name__ == "__main__":
    cli()
