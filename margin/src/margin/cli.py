from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.logging import RichHandler
from rich.spinner import Spinner

from margin.app import (
    GitHubBuildRequest,
    LocalBuildRequest,
    build_github_review,
    build_local_review,
)

logger = logging.getLogger(__name__)
STDERR_CONSOLE = Console(stderr=True)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="margin",
        description="Static snapshot code review workspace",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging and tracebacks",
    )
    parser.add_argument("--quiet", action="store_true", help="Only show errors")

    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser(
        "build",
        help="Build a review from a local directory",
    )
    build_parser.add_argument("path", type=Path, help="Local directory to review")
    build_parser.add_argument("--output", required=True, type=Path, help="Output HTML path")
    build_parser.add_argument("--title", help="Override the review title")
    build_parser.add_argument(
        "--open",
        action="store_true",
        help="Open the generated HTML in a browser",
    )

    github_parser = subparsers.add_parser(
        "build-github",
        help="Build a review from a GitHub repository",
    )
    github_parser.add_argument("repository", help="Repository in owner/repo form")
    github_parser.add_argument("--output", required=True, type=Path, help="Output HTML path")
    github_parser.add_argument("--ref", help="Branch, tag, or commit to review")
    github_parser.add_argument("--title", help="Override the review title")
    github_parser.add_argument(
        "--open",
        action="store_true",
        help="Open the generated HTML in a browser",
    )

    return parser


def configure_logging(verbose: bool, quiet: bool) -> None:
    """Configure stderr logging."""
    level = logging.INFO
    if verbose:
        level = logging.DEBUG
    elif quiet:
        level = logging.ERROR
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=STDERR_CONSOLE, rich_tracebacks=verbose, show_path=False)],
        force=True,
    )


def run_cli(argv: list[str] | None = None, stdout_console: Console | None = None) -> int:
    """Run the CLI.

    Args:
        argv: CLI arguments excluding argv[0].
        stdout_console: Optional stdout console for tests.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(verbose=args.verbose, quiet=args.quiet)
    console = stdout_console or Console(file=sys.stdout, highlight=False)

    try:
        if args.command == "build":
            with Live(
                Spinner("dots", text="Building local review..."),
                console=STDERR_CONSOLE,
                transient=True,
            ):
                result = build_local_review(
                    LocalBuildRequest(
                        root=args.path,
                        output_path=args.output,
                        title=args.title,
                        open_browser=args.open,
                    )
                )
        elif args.command == "build-github":
            with Live(
                Spinner("dots", text="Building GitHub review..."),
                console=STDERR_CONSOLE,
                transient=True,
            ):
                result = build_github_review(
                    GitHubBuildRequest(
                        repository=args.repository,
                        output_path=args.output,
                        ref=args.ref,
                        title=args.title,
                        open_browser=args.open,
                    )
                )
        else:
            parser.error("unknown command")
            return 2
    except Exception as error:
        if args.verbose:
            raise
        console.print(f"error: {error}")
        return 1

    console.print(result.output_path)
    logger.debug("Built snapshot %s with %s files", result.snapshot_id, result.file_count)
    return 0


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
