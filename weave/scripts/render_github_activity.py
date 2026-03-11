#!/usr/bin/env python3
# ruff: noqa: I001

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weave.github_activity import GitHubActivityError, main


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GitHubActivityError as exc:
        print(f"error: {exc}")
        raise SystemExit(1) from exc
