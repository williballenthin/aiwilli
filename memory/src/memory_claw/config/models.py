from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class SourceConfig(BaseModel):
    enabled: bool = True
    root: str


class LLMConfig(BaseModel):
    provider: Literal["openrouter"] = "openrouter"
    base_url: str = "https://openrouter.ai/api/v1"
    api_key_env: str = "OPENROUTER_API_KEY"
    timeout_seconds: int = 60
    max_retries: int = 1
    max_run_cost_usd: float = 2.0
    max_run_calls: int = 400


class ScheduleConfig(BaseModel):
    watcher_interval_minutes: int = 10
    extractor_interval_minutes: int = 10
    reflector_interval_minutes: int = 1440


class ExtractorContextConfig(BaseModel):
    include_global_memory: bool = True
    include_project_docs: bool = True
    project_docs_max_chars: int = 12000


class ExtractorConfig(BaseModel):
    enabled: bool = True
    primary: bool = False
    model: str = "openai/gpt-oss-120b"
    input_strategy: Literal["pairwise", "sliding_window"] = "pairwise"
    prompt: str
    window_size: int = 20
    max_chunks_per_run: int = 200
    context: ExtractorContextConfig = Field(default_factory=ExtractorContextConfig)


class ReflectorConfig(BaseModel):
    model: str = "anthropic/claude-sonnet-4"
    prompt: str = "prompts/reflector-v1.md"
    lookback_days: int = 7


class AppConfig(BaseModel):
    memory_root: str = "~/.memory-claw"
    sources: dict[str, SourceConfig]
    llm: LLMConfig = Field(default_factory=LLMConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    extractors: dict[str, ExtractorConfig]
    reflector: ReflectorConfig = Field(default_factory=ReflectorConfig)

    @property
    def root_path(self) -> Path:
        return Path(self.memory_root).expanduser().resolve()

    @classmethod
    def default(cls, memory_root: str = "~/.memory-claw") -> "AppConfig":
        return cls(
            memory_root=memory_root,
            sources={
                "pi": SourceConfig(enabled=True, root="~/.pi/agent/sessions"),
                "claude": SourceConfig(enabled=True, root="~/.claude/projects"),
            },
            llm=LLMConfig(
                provider="openrouter",
                base_url="https://openrouter.ai/api/v1",
                api_key_env="OPENROUTER_API_KEY",
                timeout_seconds=60,
                max_retries=1,
                max_run_cost_usd=2.0,
                max_run_calls=400,
            ),
            extractors={
                "pairwise-oss-120b": ExtractorConfig(
                    enabled=True,
                    primary=True,
                    model="openai/gpt-oss-120b",
                    input_strategy="pairwise",
                    prompt="prompts/pairwise-v2.md",
                    max_chunks_per_run=200,
                    context=ExtractorContextConfig(include_global_memory=True),
                )
            },
            reflector=ReflectorConfig(
                model="anthropic/claude-sonnet-4",
                prompt="prompts/reflector-v1.md",
                lookback_days=7,
            ),
        )
