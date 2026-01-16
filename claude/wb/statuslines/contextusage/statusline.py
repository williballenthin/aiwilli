#!/usr/bin/env python3
"""
Claude Code context usage status line.
Uses Claude Code's built-in context window data from stdin.
No transcript parsing needed - Claude Code provides everything directly.
"""
import sys
import json
from pathlib import Path

# ANSI color codes for terminal output
GREY = "\033[38;5;247m"  # grey69 (rgb 175,175,175)
CYAN = "\033[36m"
YELLOW = "\033[33m"
ORANGE = "\033[38;2;255;165;0m"  # rgb(255,165,0)
RED = "\033[31m"
BLUE = "\033[34m"
RESET = "\033[0m"

TOKEN_LIMIT = 200_000


def get_color_for_ratio(ratio):
    """Return ANSI color code based on usage ratio."""
    if ratio > 0.7:
        return RED
    elif ratio > 0.5:
        return ORANGE
    elif ratio > 0.3:
        return YELLOW
    else:
        return GREY


def format_path(path_str):
    """Format path with parent in grey and filename in cyan."""
    path = Path(path_str)
    filename = path.name
    parent = path.parent

    if parent and str(parent) != ".":
        return f"{GREY}{parent}/{RESET}{CYAN}{filename}{RESET}"
    else:
        return f"{CYAN}{filename}{RESET}"


def main():
    # Read JSON input from Claude Code
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        # Fallback if JSON parsing fails
        print(f"{GREY}~ 0% Unknown Model{RESET}")
        return

    # Extract data from Claude Code's built-in context_window object
    context_window = input_data.get("context_window", {})
    workspace = input_data.get("workspace", {})
    model = input_data.get("model", {})

    # Get context window size (default to 200k)
    context_size = context_window.get("context_window_size", TOKEN_LIMIT)

    # Get current usage from Claude Code's data
    current_usage = context_window.get("current_usage", {})

    # Calculate current tokens (as per Claude Code documentation)
    # Include all token types that count against the context window
    current_tokens = (
        current_usage.get("input_tokens", 0) +
        current_usage.get("cache_creation_input_tokens", 0) +
        current_usage.get("cache_read_input_tokens", 0) +
        current_usage.get("output_tokens", 0)
    )

    # Calculate ratio and percentage
    ratio = current_tokens / context_size
    percentage = int(100 * ratio)

    # Get color for percentage
    color = get_color_for_ratio(ratio)

    # Format percentage with color
    percentage_str = f"{color}{percentage}%{RESET}"

    # Get path - prefer current_dir over project_dir
    path = workspace.get("current_dir", workspace.get("project_dir", "~"))
    formatted_path = format_path(path)

    # Get model name
    model_name = model.get("display_name", "Unknown Model")
    model_str = f"{BLUE}{model_name}{RESET}"

    # Print status line (matches original output format)
    print(f"{formatted_path} {percentage_str} {model_str}")


if __name__ == "__main__":
    main()