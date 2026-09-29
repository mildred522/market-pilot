from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.commerce.contracts import CommerceAnalysisMode
from app.commerce.ingestion import CommerceImportError, import_csv_package
from app.commerce.repository import CommerceBenchmarkRepository
from app.db.session import SessionLocal, init_db


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a local public commerce benchmark CSV package")
    parser.add_argument("directory", type=Path, help="directory with the four canonical CSV files")
    parser.add_argument("--timezone", default=None, help="source timezone, if known")
    args = parser.parse_args()

    try:
        dataset = import_csv_package(
            args.directory,
            mode=CommerceAnalysisMode.BENCHMARK,
            source_type="public_dataset",
            timezone=args.timezone,
        )
        init_db()
        with SessionLocal() as db:
            persisted = CommerceBenchmarkRepository(db).save(dataset)
    except CommerceImportError as error:
        for issue in error.report.issues:
            print(f"{issue.table}:{issue.row_number or '-'} {issue.code}: {issue.message}")
        return 1
    except (OSError, ValueError) as error:
        parser.exit(1, f"benchmark import failed: {error}\n")

    print(json.dumps(persisted.snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
