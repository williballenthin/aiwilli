import os
from dataclasses import dataclass


class ConfigError(Exception):
    pass


@dataclass
class Config:
    imap_host: str
    imap_user: str
    imap_password: str
    filter_to_address: str
    allowed_senders: list[str]

    @classmethod
    def from_env(cls) -> "Config":
        """
        Load configuration from environment variables.

        Raises:
            ConfigError: If any required environment variable is missing.
        """
        required = [
            "IMAP_HOST",
            "IMAP_USER",
            "IMAP_PASSWORD",
            "FILTER_TO_ADDRESS",
            "ALLOWED_SENDERS",
        ]
        missing = [var for var in required if not os.environ.get(var)]

        if missing:
            raise ConfigError(f"Missing required env vars: {', '.join(missing)}")

        return cls(
            imap_host=os.environ["IMAP_HOST"],
            imap_user=os.environ["IMAP_USER"],
            imap_password=os.environ["IMAP_PASSWORD"],
            filter_to_address=os.environ["FILTER_TO_ADDRESS"],
            allowed_senders=[s.strip() for s in os.environ["ALLOWED_SENDERS"].split(",")],
        )
