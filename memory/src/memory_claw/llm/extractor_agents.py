from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal, cast

from memory_claw.domain.messages import NormalizedMessage
from memory_claw.domain.observations import ObservationBlock, ObservationItem
from memory_claw.llm.client import SupportsRemoteChat

EXTRACTOR_SYSTEM_PROMPT = """You are the Observer actor in memory-claw.
Follow the provided prompt sections in order.
Return only observation lines in the required format or exactly (none).
You may return any number of observation lines when justified by the input.
Do not add preambles, numbering, or any characters before '-'.
"""

OBSERVER_BACKGROUND = """
memory-claw is a global observational memory system that runs across many agent sessions and projects. Its goal is to reduce repeated self-explanation, preserve context across threads, and keep a durable record of stable working preferences. The system is intentionally filesystem-first and git-backed so humans and agents can inspect, diff, and roll back memory artifacts.

The Observer stage is where raw signal quality is won or lost. You are not summarizing task progress; you are extracting user working patterns, preferences, corrections, redirections, and durable interaction signals that will matter in future sessions. Prefer grounded evidence over speculation and prefer repeated behavioral patterns over one-off phrasing.

The downstream Reflector is conservative. Good observer output gives it clean, source-grounded signals with stable labels and compact wording, making promotion decisions safer and more accurate over time.
""".strip()

OBSERVER_FEW_SHOT = """
GOOD examples (valid output lines):
- 🔴 [preference:reinforced] User repeatedly requires behavior-first spec docs with implementation details separated into design docs. | why: values stable document boundaries that keep specs implementation-agnostic.
- 🟡 [correction] User asks to read current files before proposing edits. | why: wants grounded changes and avoids speculative modifications.
- 🟢 [redirection] User asks to sort a table by sha256 then rva for this task. | why: improves immediate task output readability.

BAD examples (do not produce):
- The user seems thoughtful and detail-oriented.            (bad: missing required format)
- 🔴 [guess] User is probably frustrated with everything.   (bad: speculative)
- [task] Assistant ran ls then grep.                        (bad: missing importance + why)
- 🟡 [preference:reinforced] User said "ok".               (bad: trivial/non-durable)
""".strip()

MAX_FORMAT_ATTEMPTS = 3


class OutputFormatError(RuntimeError):
    pass


def extract_observation_block(
    chunk: list[NormalizedMessage],
    *,
    llm_client: SupportsRemoteChat,
    model: str,
    prompt_text: str,
    include_global_memory: bool,
    global_memory_text: str,
    project_context_text: str,
    prior_observations: list[str],
) -> ObservationBlock | None:
    if not llm_client.can_use_remote():
        raise RuntimeError("remote llm is required for observation extraction")

    return _extract_with_remote(
        chunk,
        llm_client=llm_client,
        model=model,
        prompt_text=prompt_text,
        include_global_memory=include_global_memory,
        global_memory_text=global_memory_text,
        project_context_text=project_context_text,
        prior_observations=prior_observations,
    )


def _extract_with_remote(
    chunk: list[NormalizedMessage],
    *,
    llm_client: SupportsRemoteChat,
    model: str,
    prompt_text: str,
    include_global_memory: bool,
    global_memory_text: str,
    project_context_text: str,
    prior_observations: list[str],
) -> ObservationBlock | None:
    if not chunk:
        return None

    transcript = _render_chunk(chunk)
    memory_context = global_memory_text if include_global_memory else "(disabled)"
    prior_obs = "\n".join(f"- {line}" for line in prior_observations) if prior_observations else "- (none)"
    project_readme, agent_context = _split_project_context(project_context_text)

    task = _observer_task(prompt_text)
    user_prompt = "\n\n".join(
        [
            "## Your role\nYou are the Observer actor. Extract high-signal, session-grounded observations about how the user works.",
            f"## Your task\n{task}",
            "## What is coming in this prompt\n"
            "1) background context, 2) few-shot examples (good and bad), 3) project README, 4) agent context files, "
            "5) prior observations, 6) task reminder, 7) input data (messages from session), 8) final task reminder.",
            f"## Background\n{OBSERVER_BACKGROUND}",
            f"## Few-shot examples (good and bad)\n{OBSERVER_FEW_SHOT}",
            f"## Project README\n{project_readme}",
            f"## Agent context files\n{agent_context}",
            f"## Prior observations\n{prior_obs}",
            f"## Task (repeat)\n{task}",
            "## Input data (messages from session)\n"
            + transcript
            + "\n\n## Global memory context\n"
            + memory_context,
            f"## Task (repeat)\n{task}",
        ]
    )

    last_error: Exception | None = None
    for _ in range(MAX_FORMAT_ATTEMPTS):
        response_text = llm_client.chat_text(
            model=model,
            system_prompt=EXTRACTOR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
        )
        try:
            items = _parse_observation_lines_strict(response_text)
        except OutputFormatError as exc:
            last_error = exc
            continue

        if items is None:
            return None

        anchor = chunk[-1]
        return ObservationBlock(
            timestamp=anchor.timestamp if anchor.timestamp else datetime.now(timezone.utc),
            project=anchor.project,
            src_path=anchor.transcript_path,
            src_messages=[msg.source_message_id for msg in chunk],
            items=items,
        )

    raise RuntimeError(f"extractor output format invalid after retries: {last_error}")


def _observer_task(prompt_text: str) -> str:
    prompt_override = prompt_text.strip() or "(no prompt-file override provided)"
    return (
        "Extract durable, future-useful observations from this chunk. "
        "Output plain text lines only, one per observation, in this exact format: "
        "- <importance> [signal_type] summary | why: reason. "
        "Allowed importance markers are 🔴 (high), 🟡 (medium), 🟢 (low). "
        "Use 🔴 for highly durable/repeated behavior signals, 🟡 for useful but less-stable signals, and 🟢 for weak/local signals that might still matter later. "
        "The why field should capture the user's underlying intent/value in concise terms and stay grounded in the provided messages. "
        "You may emit multiple observations for a single user message when distinct signals are present. "
        "Use stable signal names when possible, avoid low-signal paraphrase, and return exactly (none) if nothing meaningful is present. "
        "Treat the following as additional actor-specific guidance:\n"
        f"{prompt_override}"
    )


def _split_project_context(project_context_text: str) -> tuple[str, str]:
    text = project_context_text.strip()
    if not text:
        return "(none found)", "(none found)"

    pattern = re.compile(r"^## Context file: (.+)$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    if not matches:
        return text, "(none found)"

    readme_sections: list[str] = []
    agent_sections: list[str] = []

    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        section = text[start:end].strip()
        header = match.group(1).strip().lower()
        name = header.split("/")[-1]

        if "readme" in name:
            readme_sections.append(section)
        elif name in {"agents.md", "claude.md"}:
            agent_sections.append(section)

    readme = "\n\n".join(readme_sections).strip() if readme_sections else "(none found)"
    agents = "\n\n".join(agent_sections).strip() if agent_sections else "(none found)"
    return readme, agents


def _parse_observation_lines_strict(response_text: str) -> list[ObservationItem] | None:
    text = response_text.strip()
    if not text:
        raise OutputFormatError("empty response")

    if text == "(none)":
        return None

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise OutputFormatError("no lines")

    items: list[ObservationItem] = []
    pattern = re.compile(r"^- (🔴|🟡|🟢) \[([^\]]+)\] (.+?) \| why: (.+)$")

    for line in lines:
        match = pattern.match(line)
        if not match:
            raise OutputFormatError(f"invalid line format: {line}")

        importance_raw = match.group(1).strip()
        if importance_raw not in {"🔴", "🟡", "🟢"}:
            raise OutputFormatError(f"invalid importance: {line}")
        importance = cast(Literal["🔴", "🟡", "🟢"], importance_raw)
        signal_type = match.group(2).strip()
        summary = match.group(3).strip()
        why = match.group(4).strip()
        if not signal_type or not summary or not why:
            raise OutputFormatError(f"missing signal/summary/why: {line}")

        if len(summary) > 420:
            summary = summary[:420].rstrip() + "…"
        if len(why) > 280:
            why = why[:280].rstrip() + "…"

        items.append(
            ObservationItem(
                importance=importance,
                signal_type=signal_type,
                summary=summary,
                why=why,
            )
        )

    return items


def _render_chunk(chunk: list[NormalizedMessage]) -> str:
    lines: list[str] = []
    for msg in chunk:
        ts = msg.timestamp.astimezone(timezone.utc).isoformat()
        text = msg.content_text.strip().replace("\n", " ")
        if len(text) > 1200:
            text = text[:1200] + "…"
        lines.append(f"[{ts}] ({msg.role}) id={msg.source_message_id}: {text}")
    return "\n".join(lines)
