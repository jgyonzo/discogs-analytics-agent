"""Batched Parquet writer wrapping pyarrow.parquet.ParquetWriter."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pyarrow as pa
import pyarrow.parquet as pq


class BatchedParquetWriter:
    """Buffers row dicts and flushes one row group when batch_size is reached.

    Use as a context manager:

        with BatchedParquetWriter(path, schema, batch_size=50_000) as w:
            for row in rows:
                w.write(row)
        # row_count is available after exit
    """

    def __init__(
        self,
        path: str | Path,
        schema: pa.Schema,
        *,
        batch_size: int = 50000,
    ) -> None:
        self.path = Path(path)
        self.schema = schema
        self.batch_size = int(batch_size)
        self._buffer: list[dict[str, Any]] = []
        self._writer: pq.ParquetWriter | None = None
        self._row_count: int = 0

    @property
    def row_count(self) -> int:
        return self._row_count

    def __enter__(self) -> "BatchedParquetWriter":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._writer = pq.ParquetWriter(self.path, self.schema)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self._flush()
        finally:
            if self._writer is not None:
                self._writer.close()
                self._writer = None

    def write(self, row: dict[str, Any]) -> None:
        self._buffer.append(row)
        if len(self._buffer) >= self.batch_size:
            self._flush()

    def write_many(self, rows: Iterable[dict[str, Any]]) -> None:
        for r in rows:
            self.write(r)

    def _flush(self) -> None:
        if not self._buffer:
            return
        if self._writer is None:
            raise RuntimeError("BatchedParquetWriter used outside its context")
        table = pa.Table.from_pylist(self._buffer, schema=self.schema)
        self._writer.write_table(table)
        self._row_count += len(self._buffer)
        self._buffer.clear()
