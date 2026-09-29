from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.commerce.repository import CommerceBenchmarkRepository
from app.commerce.sources.olist import OlistSourceAdapter
from app.commerce.warehouse import CommerceDuckDBArtifactStore
from app.db.session import SessionLocal, init_db
from app.commerce.ingestion import CommerceImportError


def main() -> int:
    parser = argparse.ArgumentParser(description="Import an Olist public benchmark dataset")
    parser.add_argument("directory", type=Path, help="directory with Olist CSV files")
    parser.add_argument("--currency", default=None, help="currency assumption for price fields, e.g. BRL")
    parser.add_argument("--timezone", default=None, help="source timezone, if known")
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=None,
        help="directory for the DuckDB artifact (defaults to COMMERCE_ARTIFACT_ROOT or backend/storage/commerce)",
    )
    args = parser.parse_args()

    adapter = OlistSourceAdapter()
    try:
        snapshot_id = adapter.snapshot_id(
            args.directory,
            currency=args.currency,
            timezone=args.timezone,
        )
        dataset = adapter.normalize(
            args.directory,
            snapshot_id=snapshot_id,
            currency=args.currency,
            timezone=args.timezone,
        )
        artifact_root = args.artifact_root or Path(
            os.getenv(
                "COMMERCE_ARTIFACT_ROOT",
                str(Path(__file__).resolve().parents[1] / "storage" / "commerce"),
            )
        )
        artifact_path = CommerceDuckDBArtifactStore(artifact_root).write(dataset)
        init_db()
        with SessionLocal() as db:
            persisted = CommerceBenchmarkRepository(db).save(dataset)
    except CommerceImportError as error:
        for issue in error.report.issues:
            print(f"{issue.table}:{issue.row_number or '-'} {issue.code}: {issue.message}")
        return 1
    except (OSError, ValueError) as error:
        parser.exit(1, f"Olist import failed: {error}\n")

    output = persisted.snapshot.model_dump(mode="json")
    output["artifact_path"] = str(artifact_path)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
