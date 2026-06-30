#!/bin/bash
set -euo pipefail

export WEAVE_VAULT_ROOT=/Users/user/Obsidian
export WEAVE_GITHUB_TIMEZONE=Europe/Berlin

WEAVE_DIR="$(cd "$(dirname "$0")/.." && pwd)"

uv --directory "$WEAVE_DIR" run weave import calendar --days 3
uv --directory "$WEAVE_DIR" run weave import github
uv --directory "$WEAVE_DIR" run weave import agent-sessions --agent-sessions /Users/user/Sync/agent-sessions --days 3
uv --directory "$WEAVE_DIR" run weave import vault-activity --days 3
uv --directory "$WEAVE_DIR" run weave import drive-activity --days 3
uv --directory "$WEAVE_DIR" run weave rebuild daily
