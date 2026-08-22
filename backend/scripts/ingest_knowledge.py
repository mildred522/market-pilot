from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

load_dotenv()

from app.db.models import Base
from app.knowledge.chunker import DeterministicKnowledgeChunker
from app.knowledge.embeddings import QwenSentenceTransformerEmbeddings
from app.knowledge.index_store import InMemoryKnowledgeIndexStore
from app.knowledge.ingestion import KnowledgeIngestionCoordinator
from app.knowledge.manifest import load_knowledge_manifest
from app.knowledge.parser import DocumentParserRouter
from app.knowledge.qdrant_store import QdrantKnowledgeIndexStore
from app.knowledge.storage import KnowledgeStorage, SecureDocumentLoader
from app.services.runtime_config import runtime_config


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest a reviewed knowledge manifest deterministically."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("restaurant_agent.db"),
    )
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--index",
        choices=("qdrant", "memory"),
        default="qdrant",
    )
    parser.add_argument(
        "--source-key",
        action="append",
        default=[],
        help="Ingest only matching source keys; may be repeated.",
    )
    parser.add_argument(
        "--skip-dense",
        action="store_true",
        help="Index BM25 only; intended for degraded development environments.",
    )
    parser.add_argument(
        "--allow-model-download",
        action="store_true",
        help="Allow dense model download during this offline ingestion run.",
    )
    parser.add_argument(
        "--allow-proxy-fake-ip",
        action="store_true",
        help=(
            "Allow the 198.18.0.0/15 DNS range used by local transparent proxies; "
            "all other private ranges remain blocked."
        ),
    )
    parser.add_argument(
        "--max-download-mb",
        type=int,
        default=25,
        choices=range(1, 101),
        metavar="1-100",
        help="Maximum reviewed source size in MiB (default: 25).",
    )
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    manifest = load_knowledge_manifest(manifest_path)
    settings = runtime_config.knowledge_rag_settings()
    storage_root = Path(args.storage_root or settings.storage_root).resolve()
    database_path = args.database.resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    index_store = (
        QdrantKnowledgeIndexStore(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            collection=settings.collection,
            dense_embedder=(
                None
                if args.skip_dense
                else QwenSentenceTransformerEmbeddings(
                    settings.dense_model,
                    local_files_only=not args.allow_model_download,
                )
            ),
        )
        if args.index == "qdrant"
        else InMemoryKnowledgeIndexStore()
    )

    with Session(engine) as db:
        coordinator = KnowledgeIngestionCoordinator(
            db,
            loader=SecureDocumentLoader(
                allow_proxy_fake_ip=args.allow_proxy_fake_ip,
                max_bytes=args.max_download_mb * 1024 * 1024,
                timeout_seconds=60,
            ),
            storage=KnowledgeStorage(storage_root),
            parser=DocumentParserRouter(),
            chunker=DeterministicKnowledgeChunker(),
            index_store=index_store,
            embedding_model=settings.dense_model,
        )
        selected = [
            entry
            for entry in manifest.documents
            if not args.source_key or entry.source.source_key in args.source_key
        ]
        unknown_keys = set(args.source_key) - {
            entry.source.source_key for entry in selected
        }
        if unknown_keys:
            parser.error(f"unknown source keys: {', '.join(sorted(unknown_keys))}")
        results = [
            coordinator.ingest(
                entry,
                manifest_directory=manifest_path.parent,
            )
            for entry in selected
        ]

    print(
        json.dumps(
            [result.model_dump(mode="json") for result in results],
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if any(result.status == "failed" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
