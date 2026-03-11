import argparse
import datetime
import os
import re
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from rich.console import Console

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

stderr = Console(stderr=True)

MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
SECTION_DATE_RE = re.compile(r"^## (\w{3}) (\d{1,2}), (\d{4})")

CONFIG_DIR = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "wballenthin" / "weave"
)
CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"
TOKEN_PATH = CONFIG_DIR / "token.json"


def get_credentials():
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json())
    return creds


def extract_section_for_date(md_text: str, target_date: datetime.date) -> str | None:
    lines = md_text.split("\n")
    sections: list[tuple[datetime.date | None, int]] = []
    for i, line in enumerate(lines):
        m = SECTION_DATE_RE.match(line)
        if m:
            month = MONTHS.get(m.group(1))
            if month:
                section_date = datetime.date(int(m.group(3)), month, int(m.group(2)))
                sections.append((section_date, i))

    for idx, (section_date, start_line) in enumerate(sections):
        if section_date != target_date:
            continue
        end_line = sections[idx + 1][1] if idx + 1 < len(sections) else len(lines)
        return "\n".join(lines[start_line:end_line]).strip()

    return None


def is_gemini_notes(att_title: str) -> bool:
    return att_title.lower().startswith("notes by gemini") or (" - Notes by Gemini" in att_title)


def is_shared_notes(att_title: str) -> bool:
    return att_title.lower().startswith("notes - ") or att_title.lower().startswith("notes -\u00a0")


def build_front_matter(
    source: str,
    event_name: str,
    start_dt: datetime.datetime,
    doc_url: str,
    event_url: str,
    attendees: list[dict],
    doc_type: str,
    attended: bool,
) -> str:
    attendee_lines = "".join(
        f'  - name: "{a.get("displayName", "")}"\n'
        f'    email: "{a["email"]}"\n'
        f'    status: "{a.get("responseStatus", "unknown")}"\n'
        for a in attendees
    )
    return (
        f"---\n"
        f'source: "{source}"\n'
        f"type: {doc_type}\n"
        f"calendar: primary\n"
        f'event: "{event_name}"\n'
        f"date: {start_dt:%Y-%m-%d}\n"
        f"attended: {'true' if attended else 'false'}\n"
        f'url: "{doc_url}"\n'
        f'event_url: "{event_url}"\n'
        f"attendees:\n{attendee_lines}"
        f"---\n\n"
    )


def main(source: str):
    creds = get_credentials()
    cal = build("calendar", "v3", credentials=creds)
    drive = build("drive", "v3", credentials=creds)

    now = datetime.datetime.now(tz=datetime.UTC)
    week_ago = (now - datetime.timedelta(days=7)).isoformat()

    with stderr.status("Fetching calendar events…", spinner="dots"):
        events = (
            cal.events()
            .list(
                calendarId="primary",
                timeMin=week_ago,
                timeMax=now.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
            .get("items", [])
        )

    stderr.print(f"Found {len(events)} events")
    exported = 0

    for event in events:
        self_attendee = next(
            (a for a in event.get("attendees", []) if a.get("self")),
            None,
        )
        if self_attendee:
            attended = self_attendee.get("responseStatus") == "accepted"
        else:
            attended = True

        start_str = event["start"].get("dateTime", event["start"].get("date"))
        start_dt = datetime.datetime.fromisoformat(start_str)
        event_name = event.get("summary", "Untitled").replace("/", "-").replace(":", "-").strip()
        event_url = event.get("htmlLink", "")
        attendees = event.get("attendees", [])
        all_attachments = event.get("attachments", [])

        doc_attachments = [
            a
            for a in all_attachments
            if a.get("mimeType") == "application/vnd.google-apps.document"
        ]
        chat_attachments = [
            a
            for a in all_attachments
            if a.get("mimeType") == "text/plain" and a.get("title", "").endswith("- Chat")
        ]

        if not doc_attachments and not chat_attachments:
            continue

        day_dir = Path("output") / f"{start_dt:%Y/%m/%d}"
        day_dir.mkdir(parents=True, exist_ok=True)
        time_prefix = f"{start_dt:%H%M}"
        base_name = f"{time_prefix} {event_name}"

        has_multiple_docs = len(doc_attachments) > 1

        for att in doc_attachments:
            file_id = att["fileId"]
            att_title = att.get("title", "")

            if has_multiple_docs and is_gemini_notes(att_title):
                name = f"{base_name} (Gemini)"
            else:
                name = base_name

            out_path = day_dir / f"{name}.md"

            if out_path.exists():
                stderr.print(f"  · {out_path} [dim]cached[/dim]")
                exported += 1
                continue

            with stderr.status(f"Exporting {out_path}", spinner="dots"):
                try:
                    md = drive.files().export(fileId=file_id, mimeType="text/markdown").execute()
                except HttpError:
                    stderr.print(f"  ✗ {out_path} [red]not accessible[/red]")
                    continue

            content = md
            if is_shared_notes(att_title):
                section = extract_section_for_date(
                    md.decode("utf-8", errors="replace"),
                    start_dt.date(),
                )
                if section is None:
                    stderr.print(f"  ✗ {out_path} [red]no section for {start_dt:%Y-%m-%d}[/red]")
                    continue
                content = section.encode("utf-8")

            doc_url = f"https://docs.google.com/document/d/{file_id}"
            front_matter = build_front_matter(
                source,
                event_name,
                start_dt,
                doc_url,
                event_url,
                attendees,
                "meeting_notes",
                attended,
            )
            out_path.write_bytes(front_matter.encode() + content)
            exported += 1
            stderr.print(f"  ✓ {out_path}")

        for att in chat_attachments:
            file_id = att["fileId"]
            name = f"{base_name} (chat)"
            out_path = day_dir / f"{name}.md"

            if out_path.exists():
                stderr.print(f"  · {out_path} [dim]cached[/dim]")
                exported += 1
                continue

            with stderr.status(f"Exporting {out_path}", spinner="dots"):
                try:
                    chat_content = drive.files().get_media(fileId=file_id).execute()
                except HttpError:
                    stderr.print(f"  ✗ {out_path} [red]not accessible[/red]")
                    continue

            doc_url = f"https://drive.google.com/file/d/{file_id}"
            front_matter = build_front_matter(
                source,
                event_name,
                start_dt,
                doc_url,
                event_url,
                attendees,
                "meeting_chat",
                attended,
            )
            out_path.write_bytes(front_matter.encode() + chat_content)
            exported += 1
            stderr.print(f"  ✓ {out_path}")

    stderr.print(f"Exported {exported} documents")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="@hex-rays.com")
    args = parser.parse_args()
    Path("output").mkdir(exist_ok=True)
    main(source=args.source)
