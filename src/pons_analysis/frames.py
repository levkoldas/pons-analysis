"""Optional dataframe and graph adapters.

Raw uint256 values are deliberately serialized as decimal strings. Neither
NumPy's fixed-width integers nor Arrow's largest standard integer type can hold
the full EVM uint256 range, so a lossy cast would be a correctness bug.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pons_analysis.core.errors import OptionalDependencyError

if TYPE_CHECKING:
    from pons_analysis.results import Table

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1


def import_optional(module: str, extra: str) -> Any:
    try:
        return __import__(module, fromlist=["*"])
    except ImportError as exc:
        raise OptionalDependencyError(
            f"Install pons-analysis[{extra}] to use {module}"
        ) from exc


def frame_values(name: str, values: Sequence[Any]) -> list[Any]:
    non_null = [value for value in values if value is not None]
    if (
        name.endswith(("_utc", "_at_utc"))
        and non_null
        and all(isinstance(value, str) for value in non_null)
    ):
        return [
            None if value in (None, "") else datetime.fromisoformat(str(value))
            for value in values
        ]
    if (
        name.endswith(("_raw", "_wei", "_tokens_raw"))
        and non_null
        and all(isinstance(value, int) for value in non_null)
    ):
        return [None if value is None else str(value) for value in values]
    if non_null and all(isinstance(value, bool) for value in non_null):
        return list(values)
    if non_null and all(isinstance(value, int) for value in non_null):
        if all(INT64_MIN <= value <= INT64_MAX for value in non_null):
            return [None if value is None else int(value) for value in values]
        return [None if value is None else str(value) for value in values]
    if non_null and all(isinstance(value, (int, float)) for value in non_null):
        return [None if value is None else float(value) for value in values]
    return [None if value is None else str(value) for value in values]


def to_polars(table: Table) -> Any:
    pl = import_optional("polars", "frames")
    columns = {name: frame_values(name, table.column(name)) for name in table.columns}
    return pl.DataFrame(columns)


def to_arrow(table: Table) -> Any:
    pa = import_optional("pyarrow", "frames")
    arrays = {
        name: pa.array(frame_values(name, table.column(name))) for name in table.columns
    }
    return pa.table(arrays)


def to_pandas(table: Table) -> Any:
    pandas = import_optional("pandas", "frames")
    return pandas.DataFrame.from_arrow(to_arrow(table))


def to_numpy(table: Table, columns: Sequence[str] | None = None) -> Any:
    import_optional("numpy", "frames")
    selected = list(table.columns if columns is None else columns)
    return to_polars(table).select(selected).to_numpy()


def to_duckdb(table: Table) -> Any:
    duckdb = import_optional("duckdb", "sql")
    if not table.columns:
        raise ValueError("Cannot create a DuckDB relation from an empty schema")
    connection = duckdb.connect(config={"TimeZone": "UTC"})
    return connection.from_arrow(to_arrow(table))


def to_networkx(
    table: Table,
    *,
    source: str,
    target: str,
    edge_attributes: Sequence[str] | None = None,
    directed: bool = True,
) -> Any:
    if source not in table.columns or target not in table.columns:
        raise ValueError("NetworkX conversion requires source and target columns")
    networkx = import_optional("networkx", "graph")
    graph = networkx.DiGraph() if directed else networkx.Graph()
    attributes = [
        name
        for name in (table.columns if edge_attributes is None else edge_attributes)
        if name not in (source, target)
    ]
    for row in table.to_dicts():
        src = row[source]
        dst = row[target]
        if src is None or dst is None:
            continue
        attrs = {
            name: row[name]
            for name in attributes
            if name in row and row[name] is not None
        }
        graph.add_edge(src, dst, **attrs)
    return graph


def to_parquet(table: Table, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    to_polars(table).write_parquet(destination)
    return destination
