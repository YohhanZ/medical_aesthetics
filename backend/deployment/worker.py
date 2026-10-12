"""Persistent projection worker; prints bounded metadata, never provider bodies/secrets."""

import json
import signal
import threading

from app.config import Settings
from app.graph_adapter import Neo4jKnowledgeGraph
from app.knowledge_worker import ProjectionWorker
from app.model_gateway import QwenEmbeddingGateway
from app.vector_adapter import MilvusVectorStore


def main() -> None:
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    settings = Settings()
    graph = Neo4jKnowledgeGraph(settings)
    gateway = QwenEmbeddingGateway(settings)
    vectors = MilvusVectorStore(settings, write=True)
    try:
        graph.setup()
        worker = ProjectionWorker(settings, graph, gateway, vectors)
        while not stop.is_set():
            try:
                result = worker.run_once()
                if result["status"] != "idle":
                    print(json.dumps(result), flush=True)
                else:
                    stop.wait(5)
            except Exception as error:
                print(
                    json.dumps({"status": "retry", "error_type": type(error).__name__}), flush=True
                )
                stop.wait(5)
    finally:
        gateway.close()
        graph.close()
        vectors.close()


if __name__ == "__main__":
    main()
