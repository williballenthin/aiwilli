import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from .config import Config, ConfigError
from .email_monitor import EmailMonitor
from .processor import Processor, TranscriptionError
from .writer import Writer

logger = logging.getLogger(__name__)
stderr_console = Console(stderr=True)


def setup_logging(verbose: bool, quiet: bool) -> None:
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=stderr_console, rich_tracebacks=verbose)],
    )


def process_batch(
    monitor: EmailMonitor,
    processor: Processor,
    writer: Writer,
    client,
    console: Console,
) -> int:
    emails = list(monitor.fetch_matching_emails(client))

    if not emails:
        return 0

    total_attachments = sum(len(e.attachments) for e in emails)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Processing emails...", total=total_attachments)

        for email_obj in emails:
            for attachment in email_obj.attachments:
                progress.update(task, description=f"Processing {attachment.filename}")

                if writer.pdf_exists(email_obj.received, attachment.filename):
                    logger.debug(f"Skipping {attachment.filename} - already exists")
                    progress.advance(task)
                    continue

                pdf_path = writer.save_pdf(email_obj, attachment)

                try:
                    content = processor.transcribe_pdf(pdf_path)
                    error = None
                except TranscriptionError as e:
                    logger.warning(f"Transcription failed: {e}")
                    content = None
                    error = str(e)

                result = writer.write_markdown(email_obj, attachment, pdf_path, content, error)

                if result.error:
                    logger.warning(f"Created error note: {result.md_path}")
                else:
                    logger.info(f"Created note: {result.md_path}")

                progress.advance(task)

            monitor.mark_as_read(client, email_obj)

    return len(emails)


def run_daemon(
    monitor: EmailMonitor,
    processor: Processor,
    writer: Writer,
    poll_interval: int,
) -> None:
    shutdown = threading.Event()
    current_client = None

    def handle_signal(signum, frame):
        stderr_console.print("[yellow]Shutting down...[/]")
        shutdown.set()
        if current_client is not None:
            try:
                current_client.logout()
            except Exception:
                pass

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while not shutdown.is_set():
        try:
            with monitor.connect() as client:
                current_client = client
                count = process_batch(monitor, processor, writer, client, stderr_console)
                if count > 0:
                    logger.info(f"Processed {count} emails")

                while not shutdown.is_set():
                    logger.debug(f"Entering IDLE (timeout={poll_interval}s)")
                    client.idle()

                    try:
                        responses = client.idle_check(timeout=poll_interval)
                    finally:
                        try:
                            client.idle_done()
                        except Exception:
                            pass

                    if shutdown.is_set():
                        break

                    if responses:
                        logger.debug(f"IDLE notification: {responses}")
                        count = process_batch(monitor, processor, writer, client, stderr_console)
                        if count > 0:
                            logger.info(f"Processed {count} emails")

                current_client = None

        except Exception as e:
            current_client = None
            if shutdown.is_set():
                break
            logger.warning(f"Connection error: {e}")
            stderr_console.print("[yellow]Reconnecting in 5s...[/]")
            time.sleep(5)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture Remarkable 2 handwritten notes via email to markdown"
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Directory to write notes",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=300,
        help="Fallback polling interval in seconds (default: 300)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only show errors",
    )
    args = parser.parse_args()

    setup_logging(args.verbose, args.quiet)

    try:
        config = Config.from_env()
    except ConfigError as e:
        stderr_console.print(f"[red]error:[/] {e}")
        sys.exit(1)

    if not args.output_dir.exists():
        stderr_console.print(f"[red]error:[/] Output directory does not exist: {args.output_dir}")
        sys.exit(1)

    monitor = EmailMonitor(config)
    processor = Processor()
    writer = Writer(args.output_dir)

    logger.info(f"Starting rm2-capture, writing to {args.output_dir}")
    run_daemon(monitor, processor, writer, args.poll_interval)


if __name__ == "__main__":
    main()
