"""Create this project's isolated authenticated Milvus configuration once."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[2]
runtime = root / "runtime"
compose_env = runtime / "m1.env"
backend_env = root / "backend" / ".env"
config_path = runtime / "milvus.yaml"
if not compose_env.exists() or not backend_env.exists():
    raise SystemExit("Run scripts.local_config first")
if config_path.exists() or "MA_MILVUS_ADMIN_TOKEN=" in backend_env.read_text("utf-8"):
    raise SystemExit("Milvus configuration already exists; preserved")
root_password, reader_password, writer_password = [secrets.token_hex(24) for _ in range(3)]
access_key, secret_key = secrets.token_hex(12), secrets.token_hex(24)
config_path.write_text(
    "etcd:\n  endpoints: [milvus-etcd:2379]\n"
    "minio:\n  address: milvus-minio\n  port: 9000\n"
    f"  accessKeyID: {access_key}\n  secretAccessKey: {secret_key}\n"
    "  useSSL: false\n  bucketName: ma-knowledge\n"
    "common:\n  security:\n    authorizationEnabled: true\n"
    f"    defaultRootPassword: '{root_password}'\n"
    "log:\n  level: error\n",
    "utf-8",
)
with compose_env.open("a", encoding="utf-8") as file:
    file.write(f"\nM2_MINIO_ACCESS_KEY={access_key}\nM2_MINIO_SECRET_KEY={secret_key}\n")
with backend_env.open("a", encoding="utf-8") as file:
    file.write(
        "\nMA_MILVUS_URI=http://127.0.0.1:59531\n"
        f"MA_MILVUS_ADMIN_TOKEN=root:{root_password}\n"
        f"MA_MILVUS_READ_TOKEN=ma_reader:{reader_password}\n"
        f"MA_MILVUS_WRITE_TOKEN=ma_worker:{writer_password}\n"
    )
print("Configured isolated authenticated Milvus and object storage; no secrets printed")
