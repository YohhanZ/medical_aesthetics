"""Append isolated local graph credentials once without changing existing settings."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[2]
compose_env = root / "runtime" / "m1.env"
backend_env = root / "backend" / ".env"
if not compose_env.exists() or not backend_env.exists():
    raise SystemExit("Run scripts.local_config first")
if "M2_GRAPH_PASSWORD=" in compose_env.read_text(
    "utf-8"
) or "MA_NEO4J_PASSWORD=" in backend_env.read_text("utf-8"):
    raise SystemExit("Graph configuration already exists; preserved")
password = secrets.token_hex(24)
with compose_env.open("a", encoding="utf-8") as file:
    file.write(f"\nM2_GRAPH_PASSWORD={password}\n")
with backend_env.open("a", encoding="utf-8") as file:
    file.write(f"\nMA_NEO4J_URI=bolt://127.0.0.1:57689\nMA_NEO4J_PASSWORD={password}\n")
print("Configured isolated local Neo4j; no credentials printed")
