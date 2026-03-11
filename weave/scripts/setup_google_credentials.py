#!/usr/bin/env python3
"""Interactive setup for Google Calendar/Drive OAuth credentials.

Runs the OAuth flow and saves the token to the XDG config directory.
Requires credentials.json to already exist at the config path.
"""
from __future__ import annotations

from weave.app import GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH, CalendarScraper


def main() -> None:
    if not GOOGLE_CREDENTIALS_PATH.exists():
        print(f"error: credentials.json not found at {GOOGLE_CREDENTIALS_PATH}")
        print("Download OAuth client credentials from Google Cloud Console and save there.")
        raise SystemExit(1)

    CalendarScraper.get_google_credentials()
    print(f"Token saved to {GOOGLE_TOKEN_PATH}")


if __name__ == "__main__":
    main()
