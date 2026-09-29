from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from collections.abc import Iterable
from pathlib import Path

import duckdb

from app.commerce.contracts import CommerceAnalysisMode, CommerceCapability
from app.commerce.ingestion import CommerceDataset
from app.commerce.snapshot import CommerceSnapshot, SnapshotState


_SAFE_SNAPSHOT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


@dataclass(frozen=True)
class DuckDBStagingTable:
    table_name: str
    source_file: str
    content_hash: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str | None, ...], ...]


class CommerceDuckDBArtifactStore:
    """Persist one validated canonical commerce dataset as a local DuckDB file."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def path_for(self, snapshot_id: str) -> Path:
        if not _SAFE_SNAPSHOT_ID.fullmatch(snapshot_id):
            raise ValueError("snapshot id contains unsupported path characters")
        return self._root / f"{snapshot_id}.duckdb"

    def write(
        self,
        dataset: CommerceDataset,
        *,
        staging_tables: Iterable[DuckDBStagingTable] = (),
    ) -> Path:
        staging_tables = tuple(staging_tables)
        target = self.path_for(dataset.snapshot.snapshot_id)
        if target.exists():
            saved = self.read_snapshot_metadata(dataset.snapshot.snapshot_id)
            if saved is None or saved.content_hash != dataset.snapshot.content_hash:
                raise ValueError("snapshot id already exists with a different DuckDB artifact")
            return target

        temp_fd, temp_name = tempfile.mkstemp(
            prefix=f".{dataset.snapshot.snapshot_id}-",
            suffix=".duckdb.tmp",
            dir=self._root,
        )
        os.close(temp_fd)
        temp_path = Path(temp_name)
        temp_path.unlink()
        try:
            with duckdb.connect(str(temp_path)) as connection:
                self._create_schema(connection)
                self._insert_dataset(connection, dataset, staging_tables=staging_tables)
                connection.execute("CHECKPOINT")
            os.replace(temp_path, target)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return target

    def read_snapshot_metadata(self, snapshot_id: str) -> CommerceSnapshot | None:
        path = self.path_for(snapshot_id)
        if not path.is_file():
            return None
        try:
            with duckdb.connect(str(path), read_only=True) as connection:
                row = connection.execute(
                    """
                    SELECT snapshot_id, mode, source_type, schema_version,
                           content_hash, created_at, period_start, period_end,
                           timezone, capabilities_json, row_counts_json
                    FROM snapshot_metadata
                    WHERE snapshot_id = ?
                    """,
                    [snapshot_id],
                ).fetchone()
        except duckdb.Error as error:
            raise ValueError("commerce DuckDB artifact is unreadable") from error
        if row is None:
            return None
        return CommerceSnapshot(
            snapshot_id=row[0],
            mode=CommerceAnalysisMode(row[1]),
            source_type=row[2],
            schema_version=row[3],
            content_hash=row[4],
            created_at=row[5],
            period_start=row[6],
            period_end=row[7],
            timezone=row[8],
            capabilities=frozenset(
                CommerceCapability(value) for value in json.loads(row[9])
            ),
            row_counts=json.loads(row[10]),
            state=SnapshotState.READY,
        )

    @staticmethod
    def _create_schema(connection: duckdb.DuckDBPyConnection) -> None:
        connection.execute(
            """
            CREATE TABLE snapshot_metadata (
                snapshot_id VARCHAR PRIMARY KEY,
                mode VARCHAR NOT NULL,
                source_type VARCHAR NOT NULL,
                schema_version VARCHAR NOT NULL,
                content_hash VARCHAR NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                period_start TIMESTAMPTZ,
                period_end TIMESTAMPTZ,
                timezone VARCHAR,
                capabilities_json VARCHAR NOT NULL,
                row_counts_json VARCHAR NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE source_files (
                source_file VARCHAR PRIMARY KEY,
                table_name VARCHAR NOT NULL,
                content_hash VARCHAR NOT NULL,
                row_count BIGINT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE products (
                product_id VARCHAR PRIMARY KEY,
                product_title VARCHAR NOT NULL,
                category_id VARCHAR,
                category_name VARCHAR,
                brand VARCHAR,
                status VARCHAR NOT NULL,
                source_file VARCHAR,
                source_row_number BIGINT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE skus (
                sku_id VARCHAR PRIMARY KEY,
                product_id VARCHAR NOT NULL,
                sku_code VARCHAR,
                variant_attributes_json VARCHAR NOT NULL,
                catalog_price DECIMAL(18, 4),
                cost_amount DECIMAL(18, 4),
                currency VARCHAR,
                source_file VARCHAR,
                source_row_number BIGINT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE orders (
                order_id VARCHAR PRIMARY KEY,
                ordered_at TIMESTAMPTZ NOT NULL,
                status VARCHAR NOT NULL,
                currency VARCHAR,
                customer_key VARCHAR,
                channel VARCHAR,
                source_file VARCHAR,
                source_row_number BIGINT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE order_items (
                order_id VARCHAR NOT NULL,
                order_item_id VARCHAR NOT NULL,
                sku_id VARCHAR NOT NULL,
                quantity DECIMAL(18, 4) NOT NULL,
                unit_price DECIMAL(18, 4) NOT NULL,
                currency VARCHAR,
                discount_amount DECIMAL(18, 4),
                refund_amount DECIMAL(18, 4),
                source_file VARCHAR,
                source_row_number BIGINT,
                PRIMARY KEY (order_id, order_item_id)
            )
            """
        )

    @staticmethod
    def _insert_dataset(
        connection: duckdb.DuckDBPyConnection,
        dataset: CommerceDataset,
        *,
        staging_tables: tuple[DuckDBStagingTable, ...],
    ) -> None:
        snapshot = dataset.snapshot
        connection.execute(
            """
            INSERT INTO snapshot_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                snapshot.snapshot_id,
                snapshot.mode.value,
                snapshot.source_type,
                snapshot.schema_version,
                snapshot.content_hash,
                snapshot.created_at,
                snapshot.period_start,
                snapshot.period_end,
                snapshot.timezone,
                json.dumps(sorted(value.value for value in snapshot.capabilities)),
                json.dumps(snapshot.row_counts, sort_keys=True),
            ],
        )
        connection.executemany(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    record.product_id,
                    record.product_title,
                    record.category_id,
                    record.category_name,
                    record.brand,
                    record.status.value,
                    record.source_file,
                    record.source_row_number,
                )
                for record in dataset.products
            ],
        )
        connection.executemany(
            "INSERT INTO skus VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    record.sku_id,
                    record.product_id,
                    record.sku_code,
                    json.dumps(record.variant_attributes, sort_keys=True),
                    record.catalog_price,
                    record.cost_amount,
                    record.currency,
                    record.source_file,
                    record.source_row_number,
                )
                for record in dataset.skus
            ],
        )
        connection.executemany(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    record.order_id,
                    record.ordered_at,
                    record.status.value,
                    record.currency,
                    record.customer_key,
                    record.channel,
                    record.source_file,
                    record.source_row_number,
                )
                for record in dataset.orders
            ],
        )
        connection.executemany(
            "INSERT INTO order_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    record.order_id,
                    record.order_item_id,
                    record.sku_id,
                    record.quantity,
                    record.unit_price,
                    record.currency,
                    record.discount_amount,
                    record.refund_amount,
                    record.source_file,
                    record.source_row_number,
                )
                for record in dataset.order_items
            ],
        )
        for table in staging_tables:
            _validate_staging_table(table)
            quoted_table = _quote_identifier(table.table_name)
            quoted_columns = ", ".join(_quote_identifier(column) for column in table.columns)
            column_definitions = ", ".join(
                f"{_quote_identifier(column)} VARCHAR" for column in table.columns
            )
            connection.execute(
                f"CREATE TABLE {quoted_table} ({column_definitions})"
            )
            if table.rows:
                placeholders = ", ".join("?" for _ in table.columns)
                connection.executemany(
                    f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})",
                    table.rows,
                )
            connection.execute(
                "INSERT INTO source_files VALUES (?, ?, ?, ?)",
                [table.source_file, table.table_name, table.content_hash, len(table.rows)],
            )


def _validate_staging_table(table: DuckDBStagingTable) -> None:
    if not _SAFE_IDENTIFIER.fullmatch(table.table_name):
        raise ValueError("staging table name contains unsupported characters")
    if not table.table_name.startswith("olist_") or not table.table_name.endswith("_staging"):
        raise ValueError("staging table name must use the olist_*_staging namespace")
    if not table.columns or len(table.columns) != len(set(table.columns)):
        raise ValueError("staging table columns must be unique and non-empty")
    if any(not _SAFE_IDENTIFIER.fullmatch(column) for column in table.columns):
        raise ValueError("staging column name contains unsupported characters")
    if any(len(row) != len(table.columns) for row in table.rows):
        raise ValueError("staging row width does not match its columns")


def _quote_identifier(value: str) -> str:
    if not _SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError("SQL identifier contains unsupported characters")
    return f'"{value}"'
