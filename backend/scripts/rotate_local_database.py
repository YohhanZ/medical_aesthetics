"""Rotate only this project's generated local DB password after a diagnostic exposure."""

import secrets
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from app.config import Settings


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    backend_env = root / "backend" / ".env"
    compose_env = root / "runtime" / "m1.env"
    settings = Settings()
    params = conninfo_to_dict(settings.database_url)
    if settings.environment != "development" or any(
        params.get(key) != expected
        for key, expected in {
            "host": "127.0.0.1",
            "port": "55434",
            "dbname": "ma_m1",
            "user": "ma_m1",
        }.items()
    ):
        raise RuntimeError("Only the named isolated development DB may rotate")
    password = secrets.token_hex(24)
    backend_text = backend_env.read_text("utf-8")
    compose_text = compose_env.read_text("utf-8")
    old = params["password"]
    if old not in backend_text or f"M1_DB_PASSWORD={old}" not in compose_text:
        raise RuntimeError("Local configuration does not match; preserved")
    # Secret values only flow through in-memory parameterized SQL and ignored local files.
    with psycopg.connect(settings.database_url, connect_timeout=5) as connection:
        connection.execute(sql.SQL("ALTER ROLE ma_m1 PASSWORD {}").format(sql.Literal(password)))
    backend_env.write_text(backend_text.replace(old, password), "utf-8")
    compose_env.write_text(
        compose_text.replace(f"M1_DB_PASSWORD={old}", f"M1_DB_PASSWORD={password}"), "utf-8"
    )
    print("Isolated local DB credential rotated; restart this task's API")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(
            f"Rotation failed: {type(error).__name__}; no connection details printed"
        ) from None
