from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from memory_claw.config.models import AppConfig
from memory_claw.io.git_ops import commit_if_dirty
from memory_claw.io.markdown_writer import atomic_write
from memory_claw.llm.client import create_client
from memory_claw.llm.reflector_agent import build_reflector_result
from memory_claw.prompts.loader import load_prompt
from memory_claw.store.repositories import StateRepository


@dataclass(slots=True)
class ReflectorRunResult:
    links_included: int = 0
    updated: bool = False
    errors: int = 0
    llm_calls: int = 0
    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0
    llm_total_tokens: int = 0
    llm_cost_usd: float = 0.0


class Reflector:
    def __init__(self, config: AppConfig, repo: StateRepository, memory_root: Path) -> None:
        self.config = config
        self.repo = repo
        self.memory_root = memory_root
        self.llm_client = create_client(config.llm)

    def run_once(self) -> ReflectorRunResult:
        result = ReflectorRunResult()
        try:
            global_memory_path = self.memory_root / "global_memory.md"
            current = global_memory_path.read_text() if global_memory_path.exists() else ""
            links, observation_context = self._collect_recent_primary_observation_materials()
            prompt_text = load_prompt(self.memory_root, self.config.reflector.prompt)

            reflector_result = build_reflector_result(
                current,
                links,
                observation_context,
                llm_client=self.llm_client,
                model=self.config.reflector.model,
                prompt_text=prompt_text,
            )
            atomic_write(global_memory_path, reflector_result.full_markdown)

            if commit_if_dirty(self.memory_root, f"reflector: {reflector_result.summary}", paths=["global_memory.md"]):
                result.updated = True
            result.links_included = len(links)

            latest_date = links[0].split("]")[0].lstrip("- [") if links else None
            self.repo.set_reflector_state(last_reflected_obs_date=latest_date)
            self.repo.commit()
        except Exception:
            result.errors += 1

        metrics = self.llm_client.get_metrics()
        result.llm_calls = metrics.calls
        result.llm_prompt_tokens = metrics.prompt_tokens
        result.llm_completion_tokens = metrics.completion_tokens
        result.llm_total_tokens = metrics.total_tokens
        result.llm_cost_usd = metrics.cost_usd
        return result

    def _collect_recent_primary_observation_materials(self) -> tuple[list[str], str]:
        lookback = self.config.reflector.lookback_days
        cutoff = date.today() - timedelta(days=max(0, lookback))
        links: list[str] = []
        context_chunks: list[str] = []
        remaining_chars = 50000

        for extractor_name, extractor_cfg in self.config.extractors.items():
            if not extractor_cfg.enabled or not extractor_cfg.primary:
                continue

            folder = self.memory_root / "observations" / extractor_name
            if not folder.exists():
                continue

            for file_path in sorted(folder.glob("*.md"), reverse=True):
                try:
                    file_date = date.fromisoformat(file_path.stem)
                except ValueError:
                    continue
                if file_date < cutoff:
                    continue

                count = self._count_blocks(file_path)
                rel = file_path.relative_to(self.memory_root)
                links.append(f"- [{file_date.isoformat()}]({rel.as_posix()}) — {count} blocks ({extractor_name})")

                if remaining_chars <= 0:
                    continue
                raw = file_path.read_text(errors="ignore")
                snippet_budget = min(7000, remaining_chars)
                snippet = raw[:snippet_budget]
                context = f"## {rel.as_posix()}\n{snippet}"
                context_chunks.append(context)
                remaining_chars -= len(context)

        combined_context = "\n\n".join(context_chunks)
        return sorted(links, reverse=True), combined_context

    @staticmethod
    def _count_blocks(file_path: Path) -> int:
        count = 0
        with file_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("## "):
                    count += 1
        return count
