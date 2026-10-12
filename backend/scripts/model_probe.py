"""Real provider probe via Model Gateway; output only safe connection metadata."""

import argparse
import json

from app.config import Settings
from app.model_gateway import GatewayError, QwenEmbeddingGateway
from scripts.authorize_knowledge_exports import PROBE_TEXT


def probe(direct: bool) -> int:
    settings = Settings()
    if direct:
        settings = settings.model_copy(update={"model_use_env_proxy": False})
    gateway = QwenEmbeddingGateway(settings)
    failed = False
    try:
        for kind in ("embedding", "chat"):
            try:
                if kind == "embedding":
                    result = {
                        "status": "connected",
                        "model": gateway.model,
                        "dimensions": len(gateway.embed(PROBE_TEXT)),
                    }
                else:
                    result = gateway.probe_chat(PROBE_TEXT)
                print(json.dumps({"kind": kind, "direct": direct, **result}))
            except GatewayError as error:
                failed = True
                print(json.dumps({"kind": kind, "code": error.code, "http_status": error.status}))
    finally:
        gateway.close()
    return int(failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--direct", action="store_true")
    raise SystemExit(probe(parser.parse_args().direct))
