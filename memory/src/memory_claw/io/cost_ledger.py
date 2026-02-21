from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _ledger_path(root: Path) -> Path:
    return root / "costs.jsonl"


def append_cost_entry(
    *,
    root: Path,
    stage: str,
    calls: int,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    cost_usd: float,
) -> None:
    path = _ledger_path(root)
    entry = {
        "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "stage": stage,
        "calls": int(calls),
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "total_tokens": int(total_tokens),
        "cost_usd": float(cost_usd),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def summarize_costs(root: Path) -> dict[str, float | int]:
    path = _ledger_path(root)
    if not path.exists():
        return {
            "entries": 0,
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
        }

    entries = 0
    calls = 0
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    cost_usd = 0.0

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            entries += 1
            calls += int(row.get("calls", 0) or 0)
            prompt_tokens += int(row.get("prompt_tokens", 0) or 0)
            completion_tokens += int(row.get("completion_tokens", 0) or 0)
            total_tokens += int(row.get("total_tokens", 0) or 0)
            cost_usd += float(row.get("cost_usd", 0.0) or 0.0)

    return {
        "entries": entries,
        "calls": calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cost_usd": cost_usd,
    }
