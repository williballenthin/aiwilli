from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from memory_claw.adapters.pi_adapter import PiTranscriptAdapter
from memory_claw.config.models import AppConfig, SourceConfig
from memory_claw.domain.messages import NormalizedMessage
from memory_claw.io.fs_paths import Paths
from memory_claw.llm.client import LLMMetrics
from memory_claw.llm.extractor_agents import extract_observation_block
from memory_claw.llm.reflector_agent import build_reflector_result
from memory_claw.pipeline.extractor_runner import ExtractorRunner, _build_pairwise_chunks
from memory_claw.pipeline.watcher import Watcher
from memory_claw.store.db import init_schema, open_db
from memory_claw.store.repositories import StateRepository


class FakeLLM:
    def __init__(
        self,
        response: str = "- 🟡 [correction] keep tests deterministic | why: prefers reliable and repeatable behavior.",
    ) -> None:
        self.response = response
        self.metrics = LLMMetrics()

    def can_use_remote(self) -> bool:
        return True

    def budget_exceeded(self) -> bool:
        return False

    def get_metrics(self) -> LLMMetrics:
        return self.metrics

    def chat_text(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        response_format: dict | None = None,
    ) -> str:
        self.metrics.calls += 1
        return self.response


class NoRemoteLLM:
    def can_use_remote(self) -> bool:
        return False

    def chat_text(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        response_format: dict | None = None,
    ) -> str:
        raise AssertionError("chat_text should not be called when remote is unavailable")


def _build_repo(memory_root: Path) -> StateRepository:
    paths = Paths(memory_root)
    conn = open_db(paths.state_db)
    init_schema(conn, paths.schema)
    return StateRepository(conn)


def _build_config(memory_root: Path, source_root: Path) -> AppConfig:
    config = AppConfig.default(memory_root=str(memory_root))
    config.sources = {
        "pi": SourceConfig(enabled=True, root=str(source_root)),
    }
    return config


def _append_jsonl(path: Path, *lines: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")


def test_pi_session_ids_are_unique_even_with_colliding_filename_suffixes(tmp_path: Path) -> None:
    memory_root = tmp_path / "memory"
    source_root = tmp_path / "sessions"

    _append_jsonl(
        source_root / "proj_a" / "2026-02-21T00-00-00Z_123.jsonl",
        '{"type":"session","cwd":"/tmp/proj-a"}',
        '{"type":"message","id":"a1","timestamp":"2026-02-21T00:00:01Z","message":{"role":"assistant","content":"A"}}',
    )
    _append_jsonl(
        source_root / "proj_b" / "2026-02-21T00-00-00Z_123.jsonl",
        '{"type":"session","cwd":"/tmp/proj-b"}',
        '{"type":"message","id":"b1","timestamp":"2026-02-21T00:00:01Z","message":{"role":"assistant","content":"B"}}',
    )

    repo = _build_repo(memory_root)
    config = _build_config(memory_root, source_root)
    watcher = Watcher(config=config, repo=repo, adapters={"pi": PiTranscriptAdapter()})

    result = watcher.run_once()
    assert result.errors == 0
    assert result.sessions_seen == 2
    assert result.messages_ingested == 2

    sessions = repo.list_sessions()
    assert len(sessions) == 2
    assert len({row.session_id for row in sessions}) == 2


def _run_pairwise_boundary_scenario(tmp_path: Path, initial_lines: list[str], appended_lines: list[str]) -> None:
    memory_root = tmp_path / "memory"
    source_root = tmp_path / "sessions"
    transcript = source_root / "proj" / "2026-02-21T00-00-00Z_test.jsonl"

    _append_jsonl(transcript, *initial_lines)

    repo = _build_repo(memory_root)
    config = _build_config(memory_root, source_root)
    watcher = Watcher(config=config, repo=repo, adapters={"pi": PiTranscriptAdapter()})
    runner = ExtractorRunner(config=config, repo=repo, memory_root=memory_root)
    runner.llm_client = FakeLLM()

    first_watch = watcher.run_once()
    assert first_watch.errors == 0
    first_extract = runner.run_once()
    assert first_extract.errors == 0
    assert first_extract.blocks_written == 0

    _append_jsonl(transcript, *appended_lines)

    second_watch = watcher.run_once()
    assert second_watch.errors == 0
    second_extract = runner.run_once()
    assert second_extract.errors == 0
    assert second_extract.blocks_written == 1

    obs_file = memory_root / "observations" / "pairwise-oss-120b" / "2026-02-21.md"
    text = obs_file.read_text()
    assert "msg:a1,u1" in text


def test_pairwise_extraction_handles_cross_run_boundary(tmp_path: Path) -> None:
    _run_pairwise_boundary_scenario(
        tmp_path,
        initial_lines=[
            '{"type":"session","cwd":"/tmp/project-x"}',
            '{"type":"message","id":"a1","timestamp":"2026-02-21T00:00:01Z","message":{"role":"assistant","content":"draft"}}',
        ],
        appended_lines=[
            '{"type":"message","id":"u1","timestamp":"2026-02-21T00:00:02Z","message":{"role":"user","content":"do not use mocks"}}',
        ],
    )


def test_pairwise_extraction_handles_tool_interleaving(tmp_path: Path) -> None:
    _run_pairwise_boundary_scenario(
        tmp_path,
        initial_lines=[
            '{"type":"session","cwd":"/tmp/project-x"}',
            '{"type":"message","id":"a1","timestamp":"2026-02-21T00:00:01Z","message":{"role":"assistant","content":"draft"}}',
            '{"type":"message","id":"t1","timestamp":"2026-02-21T00:00:02Z","message":{"role":"toolResult","content":"tool output"}}',
        ],
        appended_lines=[
            '{"type":"message","id":"u1","timestamp":"2026-02-21T00:00:03Z","message":{"role":"user","content":"do not use mocks"}}',
        ],
    )


def test_pairwise_chunks_include_first_user_turn_without_prior_assistant() -> None:
    ts = datetime(2026, 2, 21, 0, 0, tzinfo=timezone.utc)
    messages = [
        NormalizedMessage(
            source="pi",
            session_id="s1",
            source_message_id="u0",
            role="user",
            timestamp=ts,
            content_text="build a robust pipeline",
            transcript_path="/tmp/s1.jsonl",
            line_no=1,
        ),
        NormalizedMessage(
            source="pi",
            session_id="s1",
            source_message_id="a1",
            role="assistant",
            timestamp=ts,
            content_text="draft",
            transcript_path="/tmp/s1.jsonl",
            line_no=2,
        ),
        NormalizedMessage(
            source="pi",
            session_id="s1",
            source_message_id="u1",
            role="user",
            timestamp=ts,
            content_text="add tests",
            transcript_path="/tmp/s1.jsonl",
            line_no=3,
        ),
    ]

    chunks = _build_pairwise_chunks(messages)
    assert len(chunks) == 2
    assert [msg.source_message_id for msg in chunks[0]] == ["u0"]
    assert [msg.source_message_id for msg in chunks[1]] == ["a1", "u1"]


def test_extract_observation_block_allows_multiple_lines_for_single_chunk() -> None:
    ts = datetime(2026, 2, 21, 0, 0, tzinfo=timezone.utc)
    chunk = [
        NormalizedMessage(
            source="pi",
            session_id="s1",
            source_message_id="a1",
            role="assistant",
            timestamp=ts,
            content_text="draft",
            transcript_path="/tmp/s1.jsonl",
            line_no=1,
        ),
        NormalizedMessage(
            source="pi",
            session_id="s1",
            source_message_id="u1",
            role="user",
            timestamp=ts,
            content_text="do this carefully and run tests",
            transcript_path="/tmp/s1.jsonl",
            line_no=2,
        ),
    ]
    llm = FakeLLM(
        response=(
            "- 🔴 [preference:reinforced] User insists on running tests before finalizing changes. "
            "| why: values reliability and regression safety.\n"
            "- 🟡 [correction] User asks for careful execution. "
            "| why: wants reduced risk from rushed edits."
        )
    )

    block = extract_observation_block(
        chunk,
        llm_client=llm,
        model="openai/gpt-oss-120b",
        prompt_text="",
        include_global_memory=True,
        global_memory_text="",
        project_context_text="",
        prior_observations=[],
    )
    assert block is not None
    assert len(block.items) == 2


def test_extractor_cursor_does_not_advance_when_observation_write_fails(tmp_path: Path) -> None:
    memory_root = tmp_path / "memory"
    source_root = tmp_path / "sessions"
    transcript = source_root / "proj" / "2026-02-21T00-00-00Z_test.jsonl"

    _append_jsonl(
        transcript,
        '{"type":"session","cwd":"/tmp/project-x"}',
        '{"type":"message","id":"a1","timestamp":"2026-02-21T00:00:01Z","message":{"role":"assistant","content":"draft"}}',
        '{"type":"message","id":"u1","timestamp":"2026-02-21T00:00:02Z","message":{"role":"user","content":"do not use mocks"}}',
    )

    repo = _build_repo(memory_root)
    config = _build_config(memory_root, source_root)
    watcher = Watcher(config=config, repo=repo, adapters={"pi": PiTranscriptAdapter()})
    runner = ExtractorRunner(config=config, repo=repo, memory_root=memory_root)
    runner.llm_client = FakeLLM()

    watch = watcher.run_once()
    assert watch.errors == 0

    with patch(
        "memory_claw.pipeline.extractor_runner.append_observation_blocks",
        side_effect=RuntimeError("disk full"),
    ):
        extract = runner.run_once()

    assert extract.errors == 1

    session = repo.list_sessions()[0]
    cursor = repo.get_extractor_cursor("pairwise-oss-120b", session.source, session.session_id)
    assert cursor == 0


def test_remote_llm_is_required_for_extractor_and_reflector() -> None:
    ts = datetime(2026, 2, 21, 0, 0, tzinfo=timezone.utc)
    chunk = [
        NormalizedMessage(
            source="pi",
            session_id="s1",
            source_message_id="a1",
            role="assistant",
            timestamp=ts,
            content_text="draft",
            transcript_path="/tmp/s1.jsonl",
            line_no=1,
        ),
        NormalizedMessage(
            source="pi",
            session_id="s1",
            source_message_id="u1",
            role="user",
            timestamp=ts,
            content_text="do not use mocks",
            transcript_path="/tmp/s1.jsonl",
            line_no=2,
        ),
    ]

    try:
        extract_observation_block(
            chunk,
            llm_client=NoRemoteLLM(),
            model="openai/gpt-oss-120b",
            prompt_text="",
            include_global_memory=True,
            global_memory_text="",
            project_context_text="",
            prior_observations=[],
        )
    except RuntimeError as exc:
        assert "remote llm is required" in str(exc)
    else:  # pragma: no cover - defensive branch
        raise AssertionError("extract_observation_block should fail without remote LLM")

    try:
        build_reflector_result(
            current_global_memory="# Global Memory\n",
            recent_links=[],
            recent_observations_text="",
            llm_client=NoRemoteLLM(),
            model="anthropic/claude-sonnet-4",
            prompt_text="",
        )
    except RuntimeError as exc:
        assert "remote llm is required" in str(exc)
    else:  # pragma: no cover - defensive branch
        raise AssertionError("build_reflector_result should fail without remote LLM")
