"""Explicit synthetic cloud demo initialization; uses independent review/outbox services."""

import json
import os
from pathlib import Path

from app.config import Settings
from app.knowledge_import import import_dataset
from app.migrate import migrate
from app.seed import seed
from scripts.milvus_init import initialize


def main() -> None:
    settings = Settings()
    if settings.environment != "development" or not settings.allow_simulated_data:
        raise RuntimeError("Cloud demo bootstrap requires explicit development simulation")
    migrate(settings.database_url)
    print(json.dumps(seed(settings, os.environ.get("M1_SEED_PASSWORD", ""))))
    initialize(settings, include_test_collection=False)
    for name in (
        "consultation_catalog.json",
        "consultation_expanded.json",
        "demo_consultation.json",
        "empathy_knowledge.json",
    ):
        print(json.dumps({"dataset": name, **import_dataset(settings, Path("data") / name)}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(
            f"Demo bootstrap failed: {type(error).__name__}; details suppressed"
        ) from None
