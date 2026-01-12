#!/usr/bin/env python3
import sys
import json
import rich
import rich.console
from pathlib import Path

TOKEN_LIMIT = 200_000

def main():
    data = sys.stdin.read()
    doc = json.loads(data)

    transcript_path = Path(doc["transcript_path"])

    transcript = []
    for line in transcript_path.read_text(encoding="utf-8").splitlines():
        transcript.append(json.loads(line))

    current_token_usage = 0
    for entry in transcript:
        usage = entry.get("message", {}).get("usage", {})
        if not usage:
            continue

        input_tokens = usage.get("input_tokens", 0)
        create_tokens = usage.get("cache_creation_input_tokens", 0)
        read_tokens = usage.get("cache_read_input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)

        total_tokens = input_tokens + create_tokens + read_tokens + output_tokens
        if not total_tokens:
            continue

        current_token_usage = total_tokens

    model = doc["model"]["display_name"]
    cwd = doc["cwd"]

    ratio = current_token_usage / TOKEN_LIMIT
    if ratio > 0.7:
        color = "red"
    elif ratio > 0.5:
        color = "orange"
    elif ratio > 0.3:
        color = "yellow"
    else:
        color = "grey69"

    percentage = int(100 * current_token_usage / TOKEN_LIMIT)
    console = rich.console.Console(width=120, color_system="truecolor")
    console.print(f"{cwd} [{color}]{percentage}%[{color}] [blue]{model}[/blue]")

if __name__ == "__main__":
    main()
