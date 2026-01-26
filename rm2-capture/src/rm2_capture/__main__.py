import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from rich.logging import RichHandler

from .config import Config, ConfigError
from .email_monitor import EmailMonitor
from .processor import Processor, TranscriptionError
from .writer import Writer

logger = logging.getLogger(__name__)


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
        handlers=[RichHandler(rich_tracebacks=verbose)],
    )


def process_batch(
    monitor: EmailMonitor,
    processor: Processor,
    writer: Writer,
    client,
) -> int:
    emails = list(monitor.fetch_matching_emails(client))

    if not emails:
        return 0

    total_attachments = sum(len(e.attachments) for e in emails)
    logger.info(f"Found {len(emails)} emails with {total_attachments} attachments")

    processed = 0
    for email_obj in emails:
        for attachment in email_obj.attachments:
            if writer.pdf_exists(email_obj.received, attachment):
                logger.debug(f"Skipping {attachment.filename} - already exists")
                continue

            logger.info(f"Processing {attachment.filename}")

            pdf_path, pdf_filename = writer.save_pdf(email_obj, attachment)
            logger.info(f"Saved PDF to {pdf_path}")

            logger.info(f"Transcribing {attachment.filename}...")
            try:
                content = processor.transcribe_pdf(pdf_path)
                error = None
            except TranscriptionError as e:
                logger.warning(f"Transcription failed: {e}")
                content = None
                error = str(e)

            result = writer.write_markdown(email_obj, attachment, pdf_path, pdf_filename, content, error)

            if result.error:
                logger.warning(f"Created error note: {result.md_path}")
            else:
                logger.info(f"Created note: {result.md_path}")

            processed += 1

        monitor.mark_as_read(client, email_obj)

    return processed


def run_daemon(
    monitor: EmailMonitor,
    processor: Processor,
    writer: Writer,
    poll_interval: int,
) -> None:
    def handle_signal(signum, frame):
        logger.info("Shutting down...")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while True:
        try:
            with monitor.connect() as client:
                count = process_batch(monitor, processor, writer, client)
                if count > 0:
                    logger.info(f"Processed {count} attachments")

                while True:
                    logger.debug(f"Entering IDLE (timeout={poll_interval}s)")
                    client.idle()
                    responses = client.idle_check(timeout=poll_interval)
                    client.idle_done()

                    if responses:
                        logger.debug(f"IDLE notification: {responses}")
                        count = process_batch(monitor, processor, writer, client)
                        if count > 0:
                            logger.info(f"Processed {count} attachments")

        except Exception as e:
            logger.warning(f"Connection error: {e}")
            logger.info("Reconnecting in 5s...")
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
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    if not args.output_dir.exists():
        logger.error(f"Output directory does not exist: {args.output_dir}")
        sys.exit(1)

    monitor = EmailMonitor(config)
    processor = Processor()
    writer = Writer(args.output_dir)

    logger.info(f"Starting rm2-capture, writing to {args.output_dir}")
    run_daemon(monitor, processor, writer, args.poll_interval)


if __name__ == "__main__":
    main()
