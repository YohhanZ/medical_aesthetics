import hashlib
from pathlib import Path

from app.config import Settings
from app.db import transaction


def migrate(dsn: str) -> None:
    with transaction(dsn) as repo:
        repo.execute("SELECT pg_advisory_xact_lock(871230011)")
        repo.execute(
            "CREATE TABLE IF NOT EXISTS schema_revision "
            "(name text PRIMARY KEY,checksum text NOT NULL,applied_at timestamptz DEFAULT now())"
        )
        for path in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            content = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(content.encode()).hexdigest()
            row = repo.one("SELECT checksum FROM schema_revision WHERE name=%s", (path.name,))
            if row:
                if row["checksum"] != checksum:
                    raise RuntimeError("Applied migration changed; create a new migration")
                continue
            repo.execute(content)
            repo.execute(
                "INSERT INTO schema_revision(name,checksum) VALUES(%s,%s)", (path.name, checksum)
            )


if __name__ == "__main__":
    migrate(Settings().database_url)
    print("Migrations applied")
