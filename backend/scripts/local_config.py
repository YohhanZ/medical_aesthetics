"""Create ignored local credentials once; never print their values."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[2]
runtime = root / "runtime"
runtime.mkdir(exist_ok=True)
compose_env = runtime / "m1.env"
backend_env = root / "backend" / ".env"
if compose_env.exists() or backend_env.exists():
    raise SystemExit("Local configuration already exists; preserve it and follow README")
db_password = secrets.token_hex(24)
seed_password = secrets.token_urlsafe(32)
compose_env.write_text(f"M1_DB_PASSWORD={db_password}\n", encoding="utf-8")
backend_env.write_text(
    "MA_ENVIRONMENT=development\n"
    f"MA_DATABASE_URL=postgresql://ma_m1:{db_password}@127.0.0.1:55434/ma_m1\n"
    "MA_ALLOW_SIMULATED_DATA=true\nMA_COOKIE_SECURE=false\n"
    'MA_ALLOWED_ORIGINS=["http://127.0.0.1:5173","http://127.0.0.1:5175",'
    '"http://127.0.0.1:8001"]\n',
    encoding="utf-8",
)
(runtime / "m1-seed-password.txt").write_text(seed_password, encoding="utf-8")
print("Created ignored runtime/m1.env, backend/.env, runtime/m1-seed-password.txt")
