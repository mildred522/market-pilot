from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.commerce.contracts import CommerceAnalysisMode
from app.commerce.ingestion import CommerceImportError, import_csv_package
from app.commerce.repository import CommerceBenchmarkRepository
from app.commerce.warehouse import CommerceDuckDBArtifactStore
from app.db.session import SessionLocal, init_db


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a local public commerce benchmark CSV package")
    parser.add_argument("directory", type=Path, help="directory with the four canonical CSV files")
    parser.add_argument("--timezone", default=None, help="source timezone, if known")
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=None,
        help="directory for the DuckDB artifact (defaults to COMMERCE_ARTIFACT_ROOT or backend/storage/commerce)",
    )
    args = parser.parse_args()

    try:
        dataset = import_csv_package(
            args.directory,
            mode=CommerceAnalysisMode.BENCHMARK,
            source_type="public_dataset",
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
        parser.exit(1, f"benchmark import failed: {error}\n")

    output = persisted.snapshot.model_dump(mode="json")
    output["artifact_path"] = str(artifact_path)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
