"""Generate fresh isolated cloud demo secrets; preserve existing files, never print secrets."""

import argparse
import json
import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings  # noqa: E402


def write(path: Path, values: dict[str, str]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as file:
        for key, value in values.items():
            # Literal quoting is supported by python-dotenv and Compose.
            if any(character in value for character in ("\n", "\r", "'")):
                raise ValueError("Unexpected secret/configuration character")
            file.write(f"{key}='{value}'\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--docker-gid", type=int, required=True)
    args = parser.parse_args()
    target = args.destination.resolve()
    target.mkdir(parents=True, exist_ok=False)
    settings = Settings(_env_file=ROOT / "backend" / ".env")
    if not settings.model_api_key.get_secret_value():
        raise SystemExit("Model configuration missing")
    db, graph, admin, reader, writer, access, storage, seed = [
        secrets.token_hex(24) for _ in range(8)
    ]
    base = {
        "MA_ENVIRONMENT": "development",
        "MA_ALLOW_SIMULATED_DATA": "true",
        "MA_DEMO_MEDICAL_EDUCATION": "true",
        "MA_DATABASE_URL": f"postgresql://medical_demo:{db}@postgres:5432/medical_demo",
        "MA_NEO4J_URI": "bolt://neo4j:7687",
        "MA_NEO4J_PASSWORD": graph,
        "MA_MILVUS_URI": "http://milvus:19530",
        "MA_MILVUS_COLLECTION": "ma_cloud_demo_256",
        "MA_MILVUS_READ_TOKEN": f"ma_reader:{reader}",
        "LLM_MODEL": settings.chat_model,
        "LLM_URL": settings.model_base_url,
        "LLM_API_KEY": settings.model_api_key.get_secret_value(),
        "MA_MODEL_USE_ENV_PROXY": "false",
        "MA_MARKETING_IMAGE_API_KEY": settings.marketing_image_api_key.get_secret_value(),
        "MA_MARKETING_VIDEO_API_KEY": settings.marketing_video_api_key.get_secret_value(),
        "MA_MARKETING_VIDEO_ENABLED": str(settings.marketing_video_enabled).lower(),
        "MA_MARKETING_DAILY_LIMIT": str(settings.marketing_daily_limit),
        "MA_MARKETING_MEDIA_ROOT": "/app/runtime/marketing",
        "MA_MARKETING_MAX_ASSET_MB": str(settings.marketing_max_asset_mb),
        "MA_MARKETING_ASSET_HOSTS": json.dumps(settings.marketing_asset_hosts),
        "MA_MODEL_EXPORT_HASHES": json.dumps(settings.model_export_hashes),
        "LANGSMITH_TRACING": "false",
        "MA_COOKIE_SECURE": "true",
        "MA_ALLOWED_ORIGINS": '["https://43.142.39.108","https://43.142.39.108:8080"]',
        "MA_BOOKING_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "MA_BOOKING_HMAC_KEY": secrets.token_hex(32),
        "MA_BOOKING_SMS_PROVIDER": "simulated",
        "MA_AGENT_RUNTIME": "docker",
        "MA_SANDBOX_IMAGE": "medical-consultation-sandbox:demo-20261013-r2",
        "MA_SANDBOX_MAX_CONCURRENCY": "1",
        "MA_SANDBOX_MEMORY_MB": "512",
        "MA_SANDBOX_CPUS": "1",
        "MA_SANDBOX_TIMEOUT": "45",
    }
    write(
        target / "compose.env",
        {
            "DB_PASSWORD": db,
            "GRAPH_PASSWORD": graph,
            "MINIO_ACCESS_KEY": access,
            "MINIO_SECRET_KEY": storage,
            "DOCKER_GID": str(args.docker_gid),
        },
    )
    write(target / "api.env", base)
    write(target / "worker.env", {**base, "MA_MILVUS_WRITE_TOKEN": f"ma_worker:{writer}"})
    write(
        target / "bootstrap.env",
        {
            **base,
            "MA_MILVUS_WRITE_TOKEN": f"ma_worker:{writer}",
            "MA_MILVUS_ADMIN_TOKEN": f"root:{admin}",
            "M1_SEED_PASSWORD": seed,
        },
    )
    (target / "milvus.yaml").write_text(
        "etcd:\n  endpoints: [etcd:2379]\n"
        "minio:\n  address: minio\n  port: 9000\n"
        f"  accessKeyID: {access}\n  secretAccessKey: {storage}\n"
        "  useSSL: false\n  bucketName: medical-demo\n"
        "common:\n  security:\n    authorizationEnabled: true\n"
        f"    defaultRootPassword: '{admin}'\n"
        "log:\n  level: error\n",
        encoding="utf-8",
    )
    (target / "demo-access.txt").write_text(
        "演示账号：demo-author / demo-reviewer / demo-operator / demo-consultant\n"
        f"本次部署随机密码（仅合成演示环境）：{seed}\n"
        "平台管理员不自动拥有门店权限；作者不能自审。\n",
        encoding="utf-8",
    )
    print("Fresh cloud demo configuration generated; all secrets remain in ignored runtime files.")


if __name__ == "__main__":
    main()
