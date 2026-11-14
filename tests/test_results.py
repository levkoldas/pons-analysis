import csv
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import orjson
import pytest

import pons_analysis
from pons_analysis import (
    LaunchResult,
    Table,
)
from pons_analysis.storage.overlay import OverlayStore
from pons_analysis.storage.store import ArtifactStore, dumps


def test_table_infers_typed_values_and_preserves_raw_int() -> None:
    table = Table.from_rows(
        [
            {"wallet": "0xabc", "tokens_raw": 10**27, "roi_bps": -12, "ratio": 1.5},
            {"wallet": "0xdef", "tokens_raw": 2, "roi_bps": None, "ratio": 2.0},
        ]
    )
    assert table.columns == ("wallet", "tokens_raw", "roi_bps", "ratio")
    assert len(table) == 2
    assert table.column("tokens_raw") == (10**27, 2)
    assert table.to_dicts()[0]["wallet"] == "0xabc"
    frame = table.to_polars()
    assert str(frame.schema["tokens_raw"]) == "String"
    assert frame.to_dicts()[0]["tokens_raw"] == str(10**27)
    assert table.to_arrow().num_rows == 2
    assert table.to_duckdb().fetchall()[0][0] == "0xabc"


def test_duckdb_preserves_utc_timezone(monkeypatch) -> None:
    table = Table.from_rows([{"start_utc": "2026-09-06T13:18:00+00:00"}])
    value = table.to_duckdb().fetchall()[0][0]
    assert value.tzinfo is not None
    assert value.utcoffset().total_seconds() == 0
    assert value.hour == 13


def test_duckdb_uses_arrow_without_polars(monkeypatch) -> None:
    import pons_analysis.frames as frames

    def fail(_table):
        raise AssertionError("Polars should not be used")

    monkeypatch.setattr(frames, "to_polars", fail)
    table = Table.from_rows([{"a": 1}])
    assert table.to_duckdb().fetchall() == [(1,)]


def test_table_networkx_projection() -> None:
    table = Table.from_rows(
        [
            {"source": "a", "destination": "b", "value": 3},
            {"source": "b", "destination": "c", "value": 4},
        ]
    )
    graph = table.to_networkx(source="source", target="destination")
    assert graph.number_of_nodes() == 3
    assert graph.number_of_edges() == 2
    assert graph["a"]["b"]["value"] == 3


def test_table_from_csv_parses_scientific_notation_and_ragged_rows(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    path = tmp_path / "rows.csv"
    path.write_text("quote_eth,other\n1.5e-05,1\n2.0,2\n", encoding="utf-8")
    table = Table.from_csv(store, "rows.csv")
    assert table.column("quote_eth") == (1.5e-05, 2.0)
    import polars as pl

    assert table.to_polars().schema["quote_eth"] == pl.Float64
    ragged = tmp_path / "ragged.csv"
    ragged.write_text("a,b,c\n1,2\n", encoding="utf-8")
    assert Table.from_csv(store, "ragged.csv").to_dicts() == [
        {"a": 1, "b": 2, "c": None}
    ]


def test_table_from_csv_keeps_empty_as_none(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    path = tmp_path / "rows.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["wallet", "value", "empty"])
        writer.writerow(["0xabc", "7", ""])
    table = Table.from_csv(store, "rows.csv")
    assert table.to_dicts() == [{"wallet": "0xabc", "value": 7, "empty": None}]


def test_table_parquet_roundtrip(tmp_path: Path) -> None:
    table = Table.from_rows([{"a": 1, "raw": 10**40}, {"a": 2, "raw": 2}])
    path = table.to_parquet(tmp_path / "rows.parquet")
    import polars as pl

    loaded = pl.read_parquet(path)
    assert loaded.to_dicts() == table.to_polars().to_dicts()


def test_result_is_mapping_and_serializes() -> None:
    table = Table.from_rows([{"wallet": "a"}])
    result = LaunchResult(
        {"profile": "pons", "trades": 1},
        {"trades": table},
    )
    assert result["profile"] == "pons"
    assert result.trades.to_dicts() == [{"wallet": "a"}]
    payload = result.as_dict()
    assert payload["analysis"] == "launch"
    assert payload["tables"]["trades"] == [{"wallet": "a"}]


def test_result_summary_is_an_immutable_mapping() -> None:
    result = LaunchResult({"profile": "pons", "trades": 1})
    assert isinstance(result.summary, Mapping)
    with pytest.raises(TypeError):
        result.summary["trades"] = 2  # type: ignore[index]
    payload = result.as_dict()
    assert orjson.loads(dumps(payload))["summary"] == {"profile": "pons", "trades": 1}


def test_table_to_pandas_uses_the_pandas_string_dtype() -> None:
    table = Table.from_rows(
        [
            {"wallet": "0xabc", "tokens_raw": 10**27},
            {"wallet": "0xdef", "tokens_raw": 2},
        ]
    )
    frame = table.to_pandas()
    assert str(frame.dtypes["wallet"]) == "str"
    assert frame["tokens_raw"].tolist() == [str(10**27), "2"]


def test_public_facade_import_stays_lazy() -> None:
    code = (
        "import sys, pons_analysis\n"
        "assert 'pydantic' not in sys.modules, 'pydantic loaded eagerly'\n"
        "assert 'httpx' not in sys.modules, 'httpx loaded eagerly'\n"
        "for name in pons_analysis.__all__:\n"
        "    assert getattr(pons_analysis, name) is not None, name\n"
        "print('lazy')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert completed.stdout.strip() == "lazy"
    assert pons_analysis.RunConfig is not None


def test_overlay_directory_listing_falls_back_to_raw_evidence(tmp_path: Path) -> None:
    base = ArtifactStore(tmp_path / "base")
    base.write_json("evidence/funding/wallets/0xabc/meta.json", {"fresh": True})
    overlay = OverlayStore(base, tmp_path / "transient")
    assert overlay.directories("evidence/funding/wallets") == ["0xabc"]
    assert overlay.is_dir("evidence/funding/wallets")
    assert overlay.read_bytes("evidence/funding/wallets/0xabc/meta.json")


def test_overlay_hides_stale_analysis_but_reads_raw_evidence(tmp_path: Path) -> None:
    base = ArtifactStore(tmp_path / "base")
    base.write_json("evidence/launch/record.json", {"token": "raw"})
    base.write_json("analysis/positions-30/summary.json", {"minutes": 30})
    transient = tmp_path / "transient"
    overlay = OverlayStore(base, transient)
    assert overlay.read_json("evidence/launch/record.json") == {"token": "raw"}
    assert overlay.read_json("analysis/positions-30/summary.json") is None
    overlay.write_json("analysis/positions-30/summary.json", {"minutes": 60})
    assert overlay.read_json("analysis/positions-30/summary.json") == {"minutes": 60}
    assert base.read_json("analysis/positions-30/summary.json") == {"minutes": 30}


def test_frame_mixed_bool_int_is_numeric() -> None:
    table = Table.from_rows([{"flag": True}, {"flag": 1}])
    frame = table.to_polars()
    assert frame.schema["flag"].is_integer()
    assert frame.to_dicts() == [{"flag": 1}, {"flag": 1}]
    assert table.to_arrow().column("flag").to_pylist() == [1, 1]


def test_frame_empty_timestamp_is_null() -> None:
    table = Table.from_rows(
        [
            {"start_utc": ""},
            {"start_utc": "2026-09-06T13:18:00+00:00"},
        ]
    )
    assert table.to_polars().to_dicts()[0]["start_utc"] is None


def test_to_numpy_empty_column_selection() -> None:
    table = Table.from_rows([{"a": 1, "b": 2}, {"a": 3, "b": 4}])
    assert table.to_numpy([]).shape == (0, 0)


def test_table_from_rows_preserves_later_columns() -> None:
    table = Table.from_rows([{"a": 1}, {"b": 2}])
    assert table.columns == ("a", "b")
    assert table.to_dicts() == [{"a": 1, "b": None}, {"a": None, "b": 2}]


def test_networkx_empty_edge_attributes() -> None:
    table = Table.from_rows([{"source": "a", "target": "b", "value": 3}])
    graph = table.to_networkx(source="source", target="target", edge_attributes=[])
    assert graph["a"]["b"] == {}
