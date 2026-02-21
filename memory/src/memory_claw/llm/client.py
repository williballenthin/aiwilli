from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from memory_claw.config.models import LLMConfig


@dataclass(slots=True)
class LLMMetrics:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class SupportsRemoteChat(Protocol):
    def can_use_remote(self) -> bool: ...

    def chat_text(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        response_format: dict[str, Any] | None = None,
    ) -> str: ...


class LLMClient:
    """Minimal OpenAI-compatible client for OpenRouter chat completions."""

    def __init__(self, cfg: LLMConfig) -> None:
        self.provider = cfg.provider
        self.base_url = cfg.base_url.rstrip("/")
        self.api_key_env = cfg.api_key_env
        self.timeout_seconds = cfg.timeout_seconds
        self.max_retries = max(0, cfg.max_retries)
        self.max_run_cost_usd = float(cfg.max_run_cost_usd)
        self.max_run_calls = int(cfg.max_run_calls)
        self.api_key = os.getenv(cfg.api_key_env)
        self.metrics = LLMMetrics()

    def is_available(self) -> bool:
        return bool(self.api_key)

    def can_use_remote(self) -> bool:
        if not self.is_available():
            return False
        return self.provider == "openrouter"

    def budget_exceeded(self) -> bool:
        if self.metrics.calls >= self.max_run_calls:
            return True
        if self.metrics.cost_usd >= self.max_run_cost_usd:
            return True
        return False

    def get_metrics(self) -> LLMMetrics:
        return LLMMetrics(
            calls=self.metrics.calls,
            prompt_tokens=self.metrics.prompt_tokens,
            completion_tokens=self.metrics.completion_tokens,
            total_tokens=self.metrics.total_tokens,
            cost_usd=self.metrics.cost_usd,
        )

    def chat_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> dict:
        content = self.chat_text(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            response_format={"type": "json_object"},
        )

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            extracted = _extract_json_object(content)
            return json.loads(extracted)

    def chat_text(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        response_format: dict | None = None,
    ) -> str:
        if not self.can_use_remote():
            raise RuntimeError("remote llm not available")

        payload = {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if response_format is not None:
            payload["response_format"] = response_format

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._post_json(f"{self.base_url}/chat/completions", payload)
                self._record_usage(response)
                content = (
                    response.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                if not content:
                    raise RuntimeError("empty llm content")
                return str(content)
            except Exception as exc:  # pragma: no cover - network/runtime dependent
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(0.5 * (attempt + 1))

        raise RuntimeError(f"llm request failed: {last_error}")

    def _record_usage(self, response: dict) -> None:
        usage = response.get("usage")
        if not isinstance(usage, dict):
            return

        self.metrics.calls += 1
        self.metrics.prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
        self.metrics.completion_tokens += int(usage.get("completion_tokens", 0) or 0)
        self.metrics.total_tokens += int(usage.get("total_tokens", 0) or 0)
        self.metrics.cost_usd += float(usage.get("cost", 0.0) or 0.0)

    def _post_json(self, url: str, payload: dict) -> dict:
        if not self.api_key:
            raise RuntimeError(f"missing api key env: {self.api_key_env}")

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as res:  # noqa: S310
                body = res.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"http {exc.code}: {err_body}") from exc

        return json.loads(body)


def _extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise json.JSONDecodeError("no json object found", text, 0)
    return text[start : end + 1]


def create_client(cfg: LLMConfig) -> LLMClient:
    return LLMClient(cfg)
