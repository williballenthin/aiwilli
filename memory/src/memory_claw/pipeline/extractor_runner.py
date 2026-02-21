from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from memory_claw.config.models import AppConfig, ExtractorConfig
from memory_claw.domain.messages import NormalizedMessage
from memory_claw.domain.observations import ObservationBlock
from memory_claw.io.git_ops import commit_if_dirty
from memory_claw.io.markdown_writer import append_observation_blocks
from memory_claw.io.project_context import load_project_docs_context, resolve_project_root_from_chunk
from memory_claw.llm.client import create_client
from memory_claw.llm.extractor_agents import extract_observation_block
from memory_claw.prompts.loader import load_prompt
from memory_claw.store.repositories import SessionRow, StateRepository


@dataclass(slots=True)
class ExtractorRunResult:
    extractors_run: int = 0
    blocks_written: int = 0
    errors: int = 0
    llm_calls: int = 0
    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0
    llm_total_tokens: int = 0
    llm_cost_usd: float = 0.0
    llm_budget_hit: bool = False


def _build_pairwise_chunks(
    messages: list[NormalizedMessage],
    *,
    min_user_line: int = 0,
) -> list[list[NormalizedMessage]]:
    """Build user-anchored chunks for extraction.

    - Primary chunk shape is assistant->user (tool messages may occur between).
    - If a session starts with a user turn, include that first user message as a
      single-message chunk because it often captures the thread's goal.
    - `min_user_line` filters out previously processed user turns so cursor
      progression remains monotonic across runs.
    """

    chunks: list[list[NormalizedMessage]] = []
    latest_assistant: NormalizedMessage | None = None
    seen_user_turn = False

    for msg in messages:
        if msg.role == "assistant":
            latest_assistant = msg
            continue

        if msg.role != "user":
            continue

        should_process = msg.line_no > min_user_line
        if latest_assistant is not None and should_process:
            chunks.append([latest_assistant, msg])
        elif not seen_user_turn and should_process:
            chunks.append([msg])

        seen_user_turn = True
        latest_assistant = None

    return chunks


def _build_sliding_window_chunks(messages: list[NormalizedMessage], window_size: int) -> list[list[NormalizedMessage]]:
    if not messages:
        return []
    if len(messages) <= window_size:
        return [messages]

    chunks: list[list[NormalizedMessage]] = []
    step = max(1, window_size // 2)
    for start in range(0, len(messages), step):
        window = messages[start : start + window_size]
        if window:
            chunks.append(window)
        if start + window_size >= len(messages):
            break
    return chunks


class ExtractorRunner:
    def __init__(
        self,
        config: AppConfig,
        repo: StateRepository,
        memory_root: Path,
    ) -> None:
        self.config = config
        self.repo = repo
        self.memory_root = memory_root
        self.llm_client = create_client(config.llm)
        self._project_context_cache: dict[Path, str] = {}

    def run_once(self, only_extractor: str | None = None) -> ExtractorRunResult:
        result = ExtractorRunResult()
        sessions = self.repo.list_sessions()
        global_memory_text = self._truncate(self._load_global_memory_text(), 12000)

        for extractor_name, extractor_cfg in self.config.extractors.items():
            if only_extractor and extractor_name != only_extractor:
                continue
            if not extractor_cfg.enabled:
                continue
            if self.llm_client.budget_exceeded():
                result.llm_budget_hit = True
                break

            try:
                blocks = self._run_extractor_for_sessions(
                    extractor_name,
                    extractor_cfg,
                    sessions,
                    global_memory_text,
                )
                result.extractors_run += 1
                result.blocks_written += blocks
            except Exception:
                result.errors += 1

        self.repo.commit()
        metrics = self.llm_client.get_metrics()
        result.llm_calls = metrics.calls
        result.llm_prompt_tokens = metrics.prompt_tokens
        result.llm_completion_tokens = metrics.completion_tokens
        result.llm_total_tokens = metrics.total_tokens
        result.llm_cost_usd = metrics.cost_usd
        if self.llm_client.budget_exceeded():
            result.llm_budget_hit = True
        return result

    def _run_extractor_for_sessions(
        self,
        extractor_name: str,
        extractor_cfg: ExtractorConfig,
        sessions: list[SessionRow],
        global_memory_text: str,
    ) -> int:
        prompt_text = load_prompt(self.memory_root, extractor_cfg.prompt)
        all_blocks: list[ObservationBlock] = []
        pending_cursors: dict[tuple[str, str], int] = {}

        for session in sessions:
            if self.llm_client.budget_exceeded():
                break

            start = self.repo.get_extractor_cursor(extractor_name, session.source, session.session_id)
            end = session.last_ingested_line
            if end <= start:
                continue

            messages: list[NormalizedMessage]
            chunks: list[list[NormalizedMessage]]

            if extractor_cfg.input_strategy == "pairwise":
                # For pairwise extraction we read full session history and then
                # filter by min_user_line so cross-run boundaries and tool
                # interleaving do not drop assistant->user signals.
                messages = self.repo.get_messages_in_line_range(
                    source=session.source,
                    session_id=session.session_id,
                    start_line_inclusive=1,
                    end_line_inclusive=end,
                )
                chunks = _build_pairwise_chunks(messages, min_user_line=start)
            else:
                messages = self.repo.get_messages_in_line_range(
                    source=session.source,
                    session_id=session.session_id,
                    start_line_inclusive=start + 1,
                    end_line_inclusive=end,
                )
                chunks = _build_sliding_window_chunks(messages, extractor_cfg.window_size)

            if not chunks:
                pending_cursors[(session.source, session.session_id)] = end
                continue

            selected_chunks = chunks
            if extractor_cfg.max_chunks_per_run > 0 and len(chunks) > extractor_cfg.max_chunks_per_run:
                selected_chunks = chunks[: extractor_cfg.max_chunks_per_run]

            session_recent: list[str] = []
            last_processed_line = start
            for chunk in selected_chunks:
                if self.llm_client.budget_exceeded():
                    break

                project_context = ""
                if extractor_cfg.context.include_project_docs:
                    project_context = self._project_context_for_chunk(
                        chunk,
                        session,
                        max_chars=extractor_cfg.context.project_docs_max_chars,
                    )

                block = extract_observation_block(
                    chunk,
                    llm_client=self.llm_client,
                    model=extractor_cfg.model,
                    prompt_text=prompt_text,
                    include_global_memory=extractor_cfg.context.include_global_memory,
                    global_memory_text=global_memory_text,
                    project_context_text=project_context,
                    prior_observations=session_recent[-5:],
                )
                if block is not None:
                    all_blocks.append(block)
                    for item in block.items:
                        session_recent.append(
                            f"{item.importance} [{item.signal_type}] {item.summary} | why: {item.why}"
                        )
                    if len(session_recent) > 40:
                        session_recent = session_recent[-40:]
                last_processed_line = max(last_processed_line, chunk[-1].line_no)

            if last_processed_line > start:
                pending_cursors[(session.source, session.session_id)] = last_processed_line

        if all_blocks:
            append_observation_blocks(
                root=self.memory_root,
                extractor_name=extractor_name,
                prompt=extractor_cfg.prompt,
                model=extractor_cfg.model,
                blocks=all_blocks,
            )

            commit_if_dirty(
                self.memory_root,
                message=f"observations: {len(all_blocks)} from {extractor_name}",
                paths=[f"observations/{extractor_name}"],
            )

        # Cursor progression is applied only after all observation writes for
        # this extractor succeed, so failed writes cannot drop extraction state.
        for (source, session_id), line_no in pending_cursors.items():
            self.repo.set_extractor_cursor(extractor_name, source, session_id, line_no)

        return len(all_blocks)

    def _project_context_for_chunk(self, chunk: list[NormalizedMessage], session: SessionRow, max_chars: int) -> str:
        root = resolve_project_root_from_chunk(chunk)
        if root is None and session.cwd:
            cwd_path = Path(session.cwd).expanduser()
            if cwd_path.exists():
                root = cwd_path

        if root is None:
            return ""

        cached = self._project_context_cache.get(root)
        if cached is not None:
            return self._truncate(cached, max_chars)

        context = load_project_docs_context(root, max_chars=max_chars)
        self._project_context_cache[root] = context
        return context

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n...[truncated]"

    def _load_global_memory_text(self) -> str:
        path = self.memory_root / "global_memory.md"
        if not path.exists():
            return ""
        return path.read_text()
