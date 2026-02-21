from __future__ import annotations

import json
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from memory_claw.config.models import AppConfig, ExtractorConfig
from memory_claw.domain.messages import NormalizedMessage
from memory_claw.io.project_context import load_project_docs_context, resolve_project_root_from_chunk
from memory_claw.llm.client import LLMClient, LLMMetrics, create_client
from memory_claw.llm.extractor_agents import extract_observation_block
from memory_claw.llm.reflector_agent import build_reflector_result
from memory_claw.pipeline.extractor_runner import _build_pairwise_chunks, _build_sliding_window_chunks
from memory_claw.prompts.loader import load_prompt
from memory_claw.store.repositories import SessionRow, StateRepository


@dataclass(slots=True)
class LLMCallTrace:
    model: str
    system_prompt: str
    user_prompt: str
    response_text: str

    def as_dict(self) -> dict[str, str]:
        return {
            "model": self.model,
            "system_prompt": self.system_prompt,
            "user_prompt": self.user_prompt,
            "response_text": self.response_text,
        }


class TracingLLMClient:
    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner
        self.calls: list[LLMCallTrace] = []

    def can_use_remote(self) -> bool:
        return self.inner.can_use_remote()

    def budget_exceeded(self) -> bool:
        return self.inner.budget_exceeded()

    def get_metrics(self):
        return self.inner.get_metrics()

    def chat_text(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        response = self.inner.chat_text(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            response_format=response_format,
        )
        self.calls.append(
            LLMCallTrace(
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_text=response,
            )
        )
        return response


@dataclass(slots=True)
class EvalRunResult:
    run_id: str
    run_dir: Path
    observer_cases: int
    observer_success: int
    observer_errors: int
    reflector_cases: int
    reflector_errors: int
    llm_calls: int
    llm_prompt_tokens: int
    llm_completion_tokens: int
    llm_total_tokens: int
    llm_cost_usd: float


@dataclass(slots=True)
class ChunkCandidate:
    session: SessionRow
    chunk: list[NormalizedMessage]


@dataclass(slots=True)
class SessionEvalResult:
    observer_cases: list[dict[str, Any]]
    metrics: LLMMetrics


class EvaluationHarness:
    def __init__(self, config: AppConfig, repo: StateRepository, memory_root: Path) -> None:
        self.config = config
        self.repo = repo
        self.memory_root = memory_root

    def run_sample(
        self,
        *,
        sample_size: int = 12,
        seed: int = 42,
        extractor_name: str | None = None,
        workers: int = 8,
    ) -> EvalRunResult:
        if sample_size <= 0:
            raise ValueError("sample_size must be > 0")
        if workers <= 0:
            raise ValueError("workers must be > 0")

        probe_client = create_client(self.config.llm)
        if not probe_client.can_use_remote():
            raise RuntimeError("remote llm is required for evaluation")

        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = self.memory_root / "eval" / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        extractor_key, extractor_cfg = self._resolve_extractor(extractor_name)
        extractor_prompt = load_prompt(self.memory_root, extractor_cfg.prompt)
        reflector_prompt = load_prompt(self.memory_root, self.config.reflector.prompt)

        global_memory_text = self._truncate(self._load_global_memory_text(), 12000)

        candidates = self._collect_candidates(extractor_cfg)
        sampled = self._sample_candidates(candidates, sample_size=sample_size, seed=seed)

        grouped: dict[tuple[str, str], list[tuple[int, ChunkCandidate]]] = {}
        for idx, candidate in enumerate(sampled, start=1):
            key = (candidate.session.source, candidate.session.session_id)
            grouped.setdefault(key, []).append((idx, candidate))

        observer_cases: list[dict[str, Any]] = []
        observer_metrics = LLMMetrics()
        max_workers = min(workers, max(1, len(grouped)))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    self._run_session_cases,
                    entries=entries,
                    extractor_key=extractor_key,
                    extractor_cfg=extractor_cfg,
                    extractor_prompt=extractor_prompt,
                    global_memory_text=global_memory_text,
                )
                for entries in grouped.values()
            ]
            for future in as_completed(futures):
                session_result = future.result()
                observer_cases.extend(session_result.observer_cases)
                self._add_metrics(observer_metrics, session_result.metrics)

        observer_cases.sort(key=lambda case: int(case["case_id"]))

        observer_path = run_dir / "observer_cases.jsonl"
        self._write_jsonl(observer_path, observer_cases)

        reflector_case, reflector_metrics = self._run_reflector_case(
            run_id=run_id,
            observer_cases=observer_cases,
            prompt_text=reflector_prompt,
        )
        reflector_path = run_dir / "reflector_cases.jsonl"
        self._write_jsonl(reflector_path, [reflector_case])

        observer_success = sum(1 for case in observer_cases if case["parsed_items"])
        observer_errors = sum(1 for case in observer_cases if case["error"])
        reflector_errors = 1 if reflector_case.get("error") else 0

        metrics = LLMMetrics()
        self._add_metrics(metrics, observer_metrics)
        self._add_metrics(metrics, reflector_metrics)

        report_path = run_dir / "report.md"
        report_path.write_text(
            self._build_report(
                run_id=run_id,
                observer_cases=observer_cases,
                reflector_case=reflector_case,
                llm_calls=metrics.calls,
                llm_total_tokens=metrics.total_tokens,
                llm_cost_usd=metrics.cost_usd,
            )
        )

        return EvalRunResult(
            run_id=run_id,
            run_dir=run_dir,
            observer_cases=len(observer_cases),
            observer_success=observer_success,
            observer_errors=observer_errors,
            reflector_cases=1,
            reflector_errors=reflector_errors,
            llm_calls=metrics.calls,
            llm_prompt_tokens=metrics.prompt_tokens,
            llm_completion_tokens=metrics.completion_tokens,
            llm_total_tokens=metrics.total_tokens,
            llm_cost_usd=metrics.cost_usd,
        )

    def _resolve_extractor(self, requested: str | None) -> tuple[str, ExtractorConfig]:
        if requested:
            cfg = self.config.extractors.get(requested)
            if cfg is None:
                raise ValueError(f"extractor not found: {requested}")
            if not cfg.enabled:
                raise ValueError(f"extractor not enabled: {requested}")
            return requested, cfg

        for name, cfg in self.config.extractors.items():
            if cfg.enabled and cfg.primary:
                return name, cfg
        for name, cfg in self.config.extractors.items():
            if cfg.enabled:
                return name, cfg
        raise RuntimeError("no enabled extractor configured")

    def _run_session_cases(
        self,
        *,
        entries: list[tuple[int, ChunkCandidate]],
        extractor_key: str,
        extractor_cfg: ExtractorConfig,
        extractor_prompt: str,
        global_memory_text: str,
    ) -> SessionEvalResult:
        tracer = TracingLLMClient(create_client(self.config.llm))
        if not tracer.can_use_remote():
            raise RuntimeError("remote llm is required for evaluation")

        observer_cases: list[dict[str, Any]] = []
        session_recent: list[str] = []
        project_context_cache: dict[Path, str] = {}

        for case_id, candidate in sorted(entries, key=lambda row: row[0]):
            session = candidate.session
            prior = session_recent[-5:]

            project_context = ""
            if extractor_cfg.context.include_project_docs:
                project_context = self._project_context_for_chunk(
                    candidate.chunk,
                    session,
                    max_chars=extractor_cfg.context.project_docs_max_chars,
                    cache=project_context_cache,
                )

            start_calls = len(tracer.calls)
            block = None
            error = None
            try:
                block = extract_observation_block(
                    candidate.chunk,
                    llm_client=cast(LLMClient, tracer),
                    model=extractor_cfg.model,
                    prompt_text=extractor_prompt,
                    include_global_memory=extractor_cfg.context.include_global_memory,
                    global_memory_text=global_memory_text,
                    project_context_text=project_context,
                    prior_observations=prior,
                )
            except Exception as exc:  # pragma: no cover - runtime-dependent llm errors
                error = str(exc)

            attempts = [call.as_dict() for call in tracer.calls[start_calls:]]

            parsed_items: list[dict[str, str]] = []
            if block is not None:
                parsed_items = [
                    {
                        "importance": item.importance,
                        "signal_type": item.signal_type,
                        "summary": item.summary,
                        "why": item.why,
                    }
                    for item in block.items
                ]
                for item in block.items:
                    session_recent.append(
                        f"{item.importance} [{item.signal_type}] {item.summary} | why: {item.why}"
                    )
                if len(session_recent) > 40:
                    session_recent = session_recent[-40:]

            observer_cases.append(
                {
                    "case_id": case_id,
                    "extractor": extractor_key,
                    "source": session.source,
                    "session_id": session.session_id,
                    "project": session.project,
                    "cwd": session.cwd,
                    "transcript_path": session.transcript_path,
                    "chunk": [self._message_dict(msg) for msg in candidate.chunk],
                    "chunk_rendered": self._render_chunk(candidate.chunk),
                    "project_context_excerpt": self._truncate(project_context, 2500),
                    "prior_observations": prior,
                    "llm_attempts": attempts,
                    "parsed_items": parsed_items,
                    "error": error,
                }
            )

        return SessionEvalResult(observer_cases=observer_cases, metrics=tracer.get_metrics())

    def _collect_candidates(self, extractor_cfg: ExtractorConfig) -> list[ChunkCandidate]:
        candidates: list[ChunkCandidate] = []
        sessions = sorted(self.repo.list_sessions(), key=lambda row: (row.source, row.session_id))

        for session in sessions:
            if session.last_ingested_line <= 0:
                continue

            messages = self.repo.get_messages_in_line_range(
                source=session.source,
                session_id=session.session_id,
                start_line_inclusive=1,
                end_line_inclusive=session.last_ingested_line,
            )

            if extractor_cfg.input_strategy == "pairwise":
                chunks = _build_pairwise_chunks(messages)
            else:
                chunks = _build_sliding_window_chunks(messages, extractor_cfg.window_size)

            for chunk in chunks:
                if not self._is_useful_eval_chunk(chunk):
                    continue
                candidates.append(ChunkCandidate(session=session, chunk=chunk))

        return candidates

    @staticmethod
    def _is_useful_eval_chunk(chunk: list[NormalizedMessage]) -> bool:
        if not chunk:
            return False

        user_texts = [msg.content_text.strip() for msg in chunk if msg.role == "user" and msg.content_text.strip()]
        if not user_texts:
            return False

        longest_user_text = max(len(text) for text in user_texts)
        if longest_user_text < 12:
            return False

        return True

    @staticmethod
    def _sample_candidates(
        candidates: list[ChunkCandidate],
        *,
        sample_size: int,
        seed: int,
    ) -> list[ChunkCandidate]:
        if len(candidates) <= sample_size:
            return candidates

        rng = random.Random(seed)
        buckets: dict[str, list[ChunkCandidate]] = {}
        for candidate in candidates:
            buckets.setdefault(candidate.session.source, []).append(candidate)

        for bucket in buckets.values():
            rng.shuffle(bucket)

        sources = sorted(buckets.keys())
        selected: list[ChunkCandidate] = []
        target_per_source = max(1, sample_size // max(1, len(sources)))

        for source in sources:
            bucket = buckets[source]
            take = min(target_per_source, len(bucket))
            selected.extend(bucket[:take])
            buckets[source] = bucket[take:]

        while len(selected) < sample_size:
            progressed = False
            for source in sources:
                bucket = buckets[source]
                if not bucket:
                    continue
                selected.append(bucket.pop())
                progressed = True
                if len(selected) >= sample_size:
                    break
            if not progressed:
                break

        rng.shuffle(selected)
        return selected

    def _project_context_for_chunk(
        self,
        chunk: list[NormalizedMessage],
        session: SessionRow,
        *,
        max_chars: int,
        cache: dict[Path, str],
    ) -> str:
        root = resolve_project_root_from_chunk(chunk)
        if root is None and session.cwd:
            cwd_path = Path(session.cwd).expanduser()
            if cwd_path.exists():
                root = cwd_path

        if root is None:
            return ""

        cached = cache.get(root)
        if cached is not None:
            return self._truncate(cached, max_chars)

        context = load_project_docs_context(root, max_chars=max_chars)
        cache[root] = context
        return context

    def _run_reflector_case(
        self,
        *,
        run_id: str,
        observer_cases: list[dict[str, Any]],
        prompt_text: str,
    ) -> tuple[dict[str, Any], LLMMetrics]:
        recent_links = [
            (
                "- "
                f"[{datetime.now(timezone.utc).date().isoformat()}]"
                f"(eval/runs/{run_id}/observer_cases.jsonl)"
                f" — {len(observer_cases)} sampled observer cases"
            )
        ]
        recent_observations_text = self._build_recent_observation_context(observer_cases)
        current_memory = self._load_global_memory_text()

        tracer = TracingLLMClient(create_client(self.config.llm))
        if not tracer.can_use_remote():
            raise RuntimeError("remote llm is required for evaluation")

        start_calls = len(tracer.calls)
        result = None
        error = None
        try:
            result = build_reflector_result(
                current_global_memory=current_memory,
                recent_links=recent_links,
                recent_observations_text=recent_observations_text,
                llm_client=cast(LLMClient, tracer),
                model=self.config.reflector.model,
                prompt_text=prompt_text,
            )
        except Exception as exc:  # pragma: no cover - runtime-dependent llm errors
            error = str(exc)

        attempts = [call.as_dict() for call in tracer.calls[start_calls:]]

        reflector_case = {
            "case_id": 1,
            "recent_links": recent_links,
            "recent_observations_text": recent_observations_text,
            "llm_attempts": attempts,
            "result_markdown": result.full_markdown if result else "",
            "summary": result.summary if result else "",
            "error": error,
        }
        return reflector_case, tracer.get_metrics()

    @staticmethod
    def _add_metrics(target: LLMMetrics, delta: LLMMetrics) -> None:
        target.calls += delta.calls
        target.prompt_tokens += delta.prompt_tokens
        target.completion_tokens += delta.completion_tokens
        target.total_tokens += delta.total_tokens
        target.cost_usd += delta.cost_usd

    @staticmethod
    def _build_recent_observation_context(observer_cases: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for case in observer_cases:
            items = case.get("parsed_items", [])
            if not items:
                continue
            lines.append(
                f"## case-{int(case['case_id']):02d} {case['source']} {case['session_id']}"
            )
            msg_ids = [msg.get("source_message_id", "") for msg in case.get("chunk", [])]
            msg_id_text = ",".join(msg_ids) if msg_ids else "(none)"
            lines.append(f"src: {case['transcript_path']} msg:{msg_id_text}")
            lines.append("")
            for item in items:
                lines.append(
                    f"- {item['importance']} [{item['signal_type']}] {item['summary']} | why: {item['why']}"
                )
            lines.append("")

        text = "\n".join(lines)
        return text[:50000]

    @staticmethod
    def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _build_report(
        self,
        *,
        run_id: str,
        observer_cases: list[dict[str, Any]],
        reflector_case: dict[str, Any],
        llm_calls: int,
        llm_total_tokens: int,
        llm_cost_usd: float,
    ) -> str:
        lines: list[str] = [
            "# Memory Quality Evaluation Report",
            "",
            f"Run ID: `{run_id}`",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            "",
            "## Summary",
            f"- Observer cases: {len(observer_cases)}",
            f"- Observer cases with parsed observations: {sum(1 for c in observer_cases if c['parsed_items'])}",
            f"- Observer errors: {sum(1 for c in observer_cases if c['error'])}",
            f"- Reflector errors: {1 if reflector_case.get('error') else 0}",
            f"- LLM calls: {llm_calls}",
            f"- LLM tokens: {llm_total_tokens}",
            f"- LLM cost (USD): {llm_cost_usd:.6f}",
            "",
            "Use the feedback blocks below to capture good and bad quality signals.",
            "",
            "## Observer Cases",
            "",
        ]

        for case in observer_cases:
            lines.extend(
                [
                    f"### Case {int(case['case_id']):02d}",
                    f"- source: `{case['source']}`",
                    f"- session: `{case['session_id']}`",
                    f"- project: `{case.get('project') or 'unknown'}`",
                    f"- transcript: `{case['transcript_path']}`",
                    "",
                    "#### Context (sampled chunk)",
                    "```text",
                    self._truncate(case.get("chunk_rendered", ""), 1400),
                    "```",
                    "",
                ]
            )

            project_context = case.get("project_context_excerpt", "")
            if project_context:
                lines.extend(
                    [
                        "#### Project docs context (excerpt)",
                        "```text",
                        self._truncate(project_context, 1400),
                        "```",
                        "",
                    ]
                )

            prior = case.get("prior_observations", [])
            lines.append("#### Prior observations provided")
            if prior:
                for item in prior:
                    lines.append(f"- {item}")
            else:
                lines.append("- (none)")
            lines.append("")

            lines.append("#### Observer output")
            if case.get("parsed_items"):
                for item in case["parsed_items"]:
                    lines.append(
                        f"- {item['importance']} [{item['signal_type']}] {item['summary']} | why: {item['why']}"
                    )
            else:
                lines.append("- (none)")

            if case.get("error"):
                lines.append(f"- ERROR: {case['error']}")
            lines.extend(
                [
                    "",
                    "#### Feedback",
                    "- Good:",
                    "- Bad:",
                    "- Notes:",
                    "",
                ]
            )

        lines.extend(["## Reflector Case", ""])
        lines.extend(
            [
                "#### Reflector input links",
                *reflector_case.get("recent_links", []),
                "",
                "#### Reflector output (excerpt)",
                "```markdown",
                self._truncate(reflector_case.get("result_markdown", ""), 3000),
                "```",
                "",
            ]
        )

        if reflector_case.get("error"):
            lines.append(f"- ERROR: {reflector_case['error']}")
            lines.append("")

        lines.extend(
            [
                "#### Feedback",
                "- Good:",
                "- Bad:",
                "- Notes:",
                "",
            ]
        )

        return "\n".join(lines)

    @staticmethod
    def _message_dict(msg: NormalizedMessage) -> dict[str, Any]:
        return {
            "source_message_id": msg.source_message_id,
            "role": msg.role,
            "timestamp": msg.timestamp.isoformat(),
            "content_text": msg.content_text,
            "line_no": msg.line_no,
        }

    @staticmethod
    def _render_chunk(chunk: list[NormalizedMessage]) -> str:
        lines: list[str] = []
        for msg in chunk:
            text = msg.content_text.strip().replace("\n", " ")
            if len(text) > 500:
                text = text[:500] + "…"
            ts = msg.timestamp.astimezone(timezone.utc).isoformat()
            lines.append(f"[{ts}] ({msg.role}) id={msg.source_message_id}: {text}")
        return "\n".join(lines)

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
