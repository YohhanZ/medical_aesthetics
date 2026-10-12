"""Explicit local simulated booking setup; preserves existing keys and refuses real providers."""

import argparse
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import dotenv_values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enable-simulated", action="store_true", required=True)
    parser.parse_args()
    path = Path(".env")
    values = dotenv_values(path)
    environment = os.environ.get("MA_ENVIRONMENT", values.get("MA_ENVIRONMENT") or "development")
    simulated = os.environ.get(
        "MA_ALLOW_SIMULATED_DATA", values.get("MA_ALLOW_SIMULATED_DATA") or "false"
    )
    provider = os.environ.get(
        "MA_BOOKING_SMS_PROVIDER", values.get("MA_BOOKING_SMS_PROVIDER") or "disabled"
    )
    if (
        environment != "development"
        or simulated.lower() not in ("true", "1")
        or provider not in ("disabled", "simulated")
    ):
        raise RuntimeError(
            "Requires local development and simulated data; never overrides a real provider"
        )
    additions: dict[str, str] = {}
    if not values.get("MA_BOOKING_ENCRYPTION_KEY") and not os.environ.get(
        "MA_BOOKING_ENCRYPTION_KEY"
    ):
        additions["MA_BOOKING_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    if not values.get("MA_BOOKING_HMAC_KEY") and not os.environ.get("MA_BOOKING_HMAC_KEY"):
        additions["MA_BOOKING_HMAC_KEY"] = secrets.token_urlsafe(48)
    if values.get("MA_BOOKING_SMS_PROVIDER") != "simulated":
        additions["MA_BOOKING_SMS_PROVIDER"] = "simulated"
    if additions:
        with path.open("a", encoding="utf-8") as output:
            output.write("\n# Explicit M3 local simulated verification; keep keys private.\n")
            output.writelines(f"{key}={value}\n" for key, value in additions.items())
    print("Local simulated booking configured; credentials preserved and not displayed")


if __name__ == "__main__":
    main()
