from __future__ import annotations

from memory_claw.domain.memory_doc import extract_section
from memory_claw.domain.observations import ReflectorResult
from memory_claw.llm.client import SupportsRemoteChat

REFLECTOR_SYSTEM_PROMPT = """You are the Reflector actor in memory-claw.
Return the full updated global memory markdown document only.
No JSON. No code fences. No preamble.
"""

REFLECTOR_BACKGROUND = """
memory-claw maintains a global, git-backed markdown memory that is shared across many agent sessions and projects. The Reflector stage consolidates noisy short-horizon observations into a conservative, stable artifact that future sessions can trust.

Observer outputs now include an importance marker (🔴/🟡/🟢) and a short "why" rationale. Treat these as guidance for salience and intent, not as hard promotion rules. Durable memory must still be evidence-based and conservative, with wording that stays project-agnostic unless evidence shows cross-session stability.

Active context can move faster but should remain grounded in recent observations. The final document is read directly by humans and agents, so clarity, section stability, and factual traceability matter.
""".strip()

REFLECTOR_FEW_SHOT = """
GOOD patterns:
- Durable section only contains stable patterns that survive beyond one project/task.
- Importance and why fields are used as context to judge confidence and underlying intent.
- Active context summarizes current focus and recent decisions without overclaiming certainty.
- Recent observations section links to daily files and stays current.

BAD patterns:
- Promoting one-off implementation details to durable memory just because they are marked 🔴.
- Ignoring why-rationales when they explain enduring values (e.g., completeness, caution, clarity).
- Rewriting the whole file with generic fluff and dropping concrete history.
- Returning JSON, code fences, or markdown that omits required sections.
""".strip()

MAX_FORMAT_ATTEMPTS = 3


class OutputFormatError(RuntimeError):
    pass


def build_reflector_result(
    current_global_memory: str,
    recent_links: list[str],
    recent_observations_text: str,
    *,
    llm_client: SupportsRemoteChat,
    model: str,
    prompt_text: str,
) -> ReflectorResult:
    if not llm_client.can_use_remote():
        raise RuntimeError("remote llm is required for reflection")

    return _build_reflector_result_remote(
        current_global_memory=current_global_memory,
        recent_links=recent_links,
        recent_observations_text=recent_observations_text,
        llm_client=llm_client,
        model=model,
        prompt_text=prompt_text,
    )


def _build_reflector_result_remote(
    *,
    current_global_memory: str,
    recent_links: list[str],
    recent_observations_text: str,
    llm_client: SupportsRemoteChat,
    model: str,
    prompt_text: str,
) -> ReflectorResult:
    recent = "\n".join(recent_links) if recent_links else "- (none yet)"
    prior_obs = extract_section(current_global_memory, "Recent Observations")
    prior_obs_text = "\n".join(prior_obs) if prior_obs else "- (none yet)"
    task = _reflector_task(prompt_text)

    user_prompt = "\n\n".join(
        [
            "## Your role\nYou are the Reflector actor. Maintain a stable and trustworthy global memory document.",
            f"## Your task\n{task}",
            "## What is coming in this prompt\n"
            "1) background context, 2) few-shot guidance (good and bad), 3) project README, 4) agent context files, "
            "5) prior observations, 6) task reminder, 7) input data derived from session messages, 8) final task reminder.",
            f"## Background\n{REFLECTOR_BACKGROUND}",
            f"## Few-shot examples (good and bad)\n{REFLECTOR_FEW_SHOT}",
            "## Project README\n(not provided in reflector stage)",
            "## Agent context files\n(not provided in reflector stage)",
            f"## Prior observations\n{prior_obs_text}",
            f"## Task (repeat)\n{task}",
            "## Input data (messages from session)\n"
            "The reflector receives session-derived observation artifacts rather than raw chat messages.\n\n"
            "### Current global_memory.md\n"
            + (current_global_memory or "(empty)")
            + "\n\n### Recent observation links\n"
            + recent
            + "\n\n### Recent observation contents\n"
            + (recent_observations_text or "(none)")
            + "\n",
            f"## Task (repeat)\n{task}",
        ]
    )

    last_error: Exception | None = None
    for _ in range(MAX_FORMAT_ATTEMPTS):
        response_text = llm_client.chat_text(
            model=model,
            system_prompt=REFLECTOR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
        )

        try:
            full_markdown = _parse_markdown_strict(response_text)
        except OutputFormatError as exc:
            last_error = exc
            continue

        return ReflectorResult(
            full_markdown=full_markdown,
            summary=f"remote markdown update ({len(recent_links)} links)",
        )

    raise RuntimeError(f"reflector output format invalid after retries: {last_error}")


def _reflector_task(prompt_text: str) -> str:
    prompt_override = prompt_text.strip() or "(no prompt-file override provided)"
    return (
        "Update the full global_memory.md markdown document. Preserve the required structure exactly: "
        "# Global Memory, ## Durable Preferences and Patterns, ## Active Context, ## Recent Observations. "
        "Use observation importance (🔴/🟡/🟢) and why-rationales as qualitative context: prioritize strong, repeated value-level signals, "
        "and avoid promoting project-local implementation details into durable memory. "
        "Be conservative about durable promotion, keep active context current, and return markdown only with no JSON or code fences. "
        "Treat the following as additional actor-specific guidance:\n"
        f"{prompt_override}"
    )


def _parse_markdown_strict(response_text: str) -> str:
    text = response_text.strip()
    if not text:
        raise OutputFormatError("empty response")

    if text.startswith("{"):
        raise OutputFormatError("json response not allowed")
    if "```" in text:
        raise OutputFormatError("code fences not allowed")

    lines = [line for line in text.splitlines() if line.strip()]
    if not lines or lines[0].strip() != "# Global Memory":
        raise OutputFormatError("first non-empty line must be '# Global Memory'")

    required = [
        "## Durable Preferences and Patterns",
        "## Active Context",
        "## Recent Observations",
    ]
    for marker in required:
        if marker not in text:
            raise OutputFormatError(f"missing required section: {marker}")

    return text
