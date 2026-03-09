import importlib.util
import logging
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path


MODULE_PATH = Path("/home/runner/work/aiwilli/aiwilli/scripts/vnote-pipe-obsidian.py")
SPEC = importlib.util.spec_from_file_location("vnote_pipe_obsidian", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None

imapclient_module = types.ModuleType("imapclient")
imapclient_module.IMAPClient = object
sys.modules.setdefault("imapclient", imapclient_module)

rich_module = types.ModuleType("rich")
rich_logging_module = types.ModuleType("rich.logging")


class RichHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        pass


rich_logging_module.RichHandler = RichHandler
rich_module.logging = rich_logging_module
sys.modules.setdefault("rich", rich_module)
sys.modules.setdefault("rich.logging", rich_logging_module)

VNOTE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VNOTE
SPEC.loader.exec_module(VNOTE)


class WriterCollisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.output_dir = Path(self.tmpdir.name)
        self.writer = VNOTE.Writer(self.output_dir)
        self.received = datetime(2026, 3, 9, 10, 52, 0)

    def make_email(
        self,
        uid: int,
        body: str,
        attachments: list[VNOTE.Attachment] | None = None,
    ) -> VNOTE.IncomingEmail:
        return VNOTE.IncomingEmail(
            uid=uid,
            subject="Voice Note",
            received=self.received,
            body=body,
            attachments=attachments or [],
        )

    def test_note_exists_is_uid_based_not_timestamp_based(self) -> None:
        first_email = self.make_email(uid=1, body="first half")
        second_email = self.make_email(uid=2, body="second half")

        self.writer.write_note(first_email)

        self.assertTrue(self.writer.note_exists(first_email))
        self.assertFalse(self.writer.note_exists(second_email))

    def test_writer_keeps_both_same_minute_transcriptions(self) -> None:
        first_email = self.make_email(uid=1, body="first half")
        second_email = self.make_email(uid=2, body="second half")

        first_result = self.writer.write_note(first_email)
        second_result = self.writer.write_note(second_email)

        self.assertNotEqual(first_result.md_path, second_result.md_path)
        self.assertEqual("1052 - transcription.md", first_result.md_path.name)
        self.assertEqual("1052-2 - transcription.md", second_result.md_path.name)
        self.assertIn("uid: 1", first_result.md_path.read_text(encoding="utf-8"))
        self.assertIn("first half", first_result.md_path.read_text(encoding="utf-8"))
        self.assertIn("uid: 2", second_result.md_path.read_text(encoding="utf-8"))
        self.assertIn("second half", second_result.md_path.read_text(encoding="utf-8"))

    def test_attachment_names_stay_unique_across_same_minute_notes(self) -> None:
        attachment_name = "clip.m4a"
        first_email = self.make_email(
            uid=1,
            body="first half",
            attachments=[VNOTE.Attachment(filename=attachment_name, content=b"first")],
        )
        second_email = self.make_email(
            uid=2,
            body="second half",
            attachments=[VNOTE.Attachment(filename=attachment_name, content=b"second")],
        )

        first_result = self.writer.write_note(first_email)
        second_result = self.writer.write_note(second_email)

        self.assertEqual("1052 - clip.m4a", first_result.attachment_paths[0].name)
        self.assertEqual("1052-2 - clip.m4a", second_result.attachment_paths[0].name)
        self.assertEqual(b"first", first_result.attachment_paths[0].read_bytes())
        self.assertEqual(b"second", second_result.attachment_paths[0].read_bytes())


class ProcessBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.writer = VNOTE.Writer(Path(self.tmpdir.name))
        received = datetime(2026, 3, 9, 10, 52, 0)
        self.emails = [
            VNOTE.IncomingEmail(
                uid=1,
                subject="Voice Note",
                received=received,
                body="first half",
                attachments=[],
            ),
            VNOTE.IncomingEmail(
                uid=2,
                subject="Voice Note",
                received=received,
                body="second half",
                attachments=[],
            ),
        ]

    def test_process_batch_writes_both_same_minute_emails(self) -> None:
        marked_as_read: list[int] = []

        class Monitor:
            def __init__(self, emails: list[VNOTE.IncomingEmail]):
                self._emails = emails

            def fetch_matching_emails(self, client) -> list[VNOTE.IncomingEmail]:
                return list(self._emails)

            def mark_as_read(self, client, email_obj: VNOTE.IncomingEmail) -> None:
                marked_as_read.append(email_obj.uid)

        processed = VNOTE.process_batch(Monitor(self.emails), self.writer, client=object())

        self.assertEqual(2, processed)
        self.assertEqual([1, 2], marked_as_read)
        note_files = sorted((Path(self.tmpdir.name) / "2026-03-09").glob("*.md"))
        self.assertEqual(
            ["1052 - transcription.md", "1052-2 - transcription.md"],
            [path.name for path in note_files],
        )


if __name__ == "__main__":
    unittest.main()
