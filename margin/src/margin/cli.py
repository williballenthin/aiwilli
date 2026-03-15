from __future__ import annotations

import argparse
import logging
import sys
import tempfile
import webbrowser
from contextlib import ExitStack
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
from margin.server import build_review_url, run_http_server

logger = logging.getLogger(__name__)
STDERR_CONSOLE = Console(stderr=True)
DEFAULT_SERVE_HOST = "127.0.0.1"
DEFAULT_SERVE_PORT = 5174
DEFAULT_SERVE_ARTIFACT_NAME = "review.html"


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

    serve_parser = subparsers.add_parser(
        "serve",
        help="Build a local review and serve it over HTTP",
    )
    serve_parser.add_argument("path", type=Path, help="Local directory to review")
    serve_parser.add_argument("--title", help="Override the review title")
    serve_parser.add_argument("--host", default=DEFAULT_SERVE_HOST, help="HTTP bind host")
    serve_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_SERVE_PORT,
        help="HTTP bind port",
    )
    serve_parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory where review.html should be written before serving",
    )
    serve_parser.add_argument(
        "--open",
        action="store_true",
        help="Open the served review URL in a browser",
    )

    serve_github_parser = subparsers.add_parser(
        "serve-github",
        help="Build a GitHub review and serve it over HTTP",
    )
    serve_github_parser.add_argument("repository", help="Repository in owner/repo form")
    serve_github_parser.add_argument("--ref", help="Branch, tag, or commit to review")
    serve_github_parser.add_argument("--title", help="Override the review title")
    serve_github_parser.add_argument("--host", default=DEFAULT_SERVE_HOST, help="HTTP bind host")
    serve_github_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_SERVE_PORT,
        help="HTTP bind port",
    )
    serve_github_parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory where review.html should be written before serving",
    )
    serve_github_parser.add_argument(
        "--open",
        action="store_true",
        help="Open the served review URL in a browser",
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


def get_serve_output_path(stack: ExitStack, output_dir: Path | None) -> Path:
    """Resolve the output artifact path for a served review.

    Args:
        stack: Exit stack that owns any temporary directory lifetime.
        output_dir: Optional persistent output directory.
    """
    if output_dir is None:
        root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="margin-serve-")))
    else:
        root = output_dir.resolve()
        root.mkdir(parents=True, exist_ok=True)
    return root / DEFAULT_SERVE_ARTIFACT_NAME


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
            console.print(result.output_path)
            logger.debug("Built snapshot %s with %s files", result.snapshot_id, result.file_count)
            return 0

        if args.command == "build-github":
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
            console.print(result.output_path)
            logger.debug("Built snapshot %s with %s files", result.snapshot_id, result.file_count)
            return 0

        if args.command == "serve":
            with ExitStack() as stack:
                output_path = get_serve_output_path(stack, args.output_dir)
                with Live(
                    Spinner("dots", text="Building local review..."),
                    console=STDERR_CONSOLE,
                    transient=True,
                ):
                    build_local_review(
                        LocalBuildRequest(
                            root=args.path,
                            output_path=output_path,
                            title=args.title,
                            open_browser=False,
                        )
                    )
                review_url = build_review_url(args.host, args.port, output_path.name)
                logger.info("Serving %s at %s", output_path, review_url)
                if args.open:
                    webbrowser.open(review_url)
                console.print(review_url)
                run_http_server(output_path.parent, args.host, args.port)
            return 0

        if args.command == "serve-github":
            with ExitStack() as stack:
                output_path = get_serve_output_path(stack, args.output_dir)
                with Live(
                    Spinner("dots", text="Building GitHub review..."),
                    console=STDERR_CONSOLE,
                    transient=True,
                ):
                    build_github_review(
                        GitHubBuildRequest(
                            repository=args.repository,
                            output_path=output_path,
                            ref=args.ref,
                            title=args.title,
                            open_browser=False,
                        )
                    )
                review_url = build_review_url(args.host, args.port, output_path.name)
                logger.info("Serving %s at %s", output_path, review_url)
                if args.open:
                    webbrowser.open(review_url)
                console.print(review_url)
                run_http_server(output_path.parent, args.host, args.port)
            return 0

        parser.error("unknown command")
        return 2
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        if args.verbose:
            raise
        console.print(f"error: {error}")
        return 1


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
