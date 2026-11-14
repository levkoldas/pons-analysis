import pytest

from pons_analysis import MigrationCut, Pons
from pons_analysis.core.errors import InvariantError
from pons_analysis.presentation.report import render_report
from pons_analysis.presentation.report.loader import (
    _reject_markup,
    read_csv_artifact,
)
from pons_analysis.storage.store import ArtifactStore


def launch():
    return Pons.launch(
        token="0x" + "11" * 20,
        supply=1,
        start_block=10,
        start_timestamp=1,
        migration=MigrationCut(block=10, tx_index=0, log_index=0),
    )


def test_report_rejects_non_html_destination(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    with pytest.raises(InvariantError):
        render_report(store, launch(), minutes=30, output="analysis/report.json")


def test_report_rejects_destinations_outside_analysis(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    with pytest.raises(InvariantError):
        render_report(store, launch(), minutes=30, output="evidence/report.html")
    with pytest.raises(InvariantError):
        render_report(store, launch(), minutes=30, output="report.html")


def test_report_refuses_to_overwrite_non_report_json(tmp_path, monkeypatch) -> None:
    from pons_analysis.presentation.report import renderer

    store = ArtifactStore(tmp_path)
    store.write_json("analysis/foo.json", {"not": "a report"})
    monkeypatch.setattr(renderer, "load_report_data", lambda *args, **kwargs: ({}, {}))
    with pytest.raises(InvariantError):
        render_report(store, launch(), minutes=30, output="analysis/foo.html")


def test_report_normalizes_paths_before_source_collision_check(
    tmp_path, monkeypatch
) -> None:
    from pons_analysis.presentation.report import renderer

    store = ArtifactStore(tmp_path)
    monkeypatch.setattr(
        renderer,
        "load_report_data",
        lambda *args, **kwargs: (
            {},
            {"analysis/launch/summary.json": {"bytes": 1, "sha256": "0x" + "00" * 32}},
        ),
    )
    with pytest.raises(InvariantError):
        render_report(
            store,
            launch(),
            minutes=30,
            output="analysis/launch/../launch/summary.html",
        )


def test_report_markup_preflight() -> None:
    with pytest.raises(InvariantError):
        _reject_markup({"metric": "<img src=x onerror=alert(1)>"})
    _reject_markup({"metric": "safe"})


def test_header_only_required_csv_is_not_missing(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_csv("analysis/empty.csv", [], fields=["a"])
    assert read_csv_artifact(store, "analysis/empty.csv", "test") == []


def test_report_requires_html_extension(tmp_path, monkeypatch) -> None:
    from pons_analysis.presentation.report import renderer

    store = ArtifactStore(tmp_path)
    monkeypatch.setattr(renderer, "load_report_data", lambda *args, **kwargs: ({}, {}))
    with pytest.raises(InvariantError):
        render_report(store, launch(), minutes=30, output="analysis/report.json")


def test_report_defines_every_chart_color() -> None:
    import inspect
    import re

    from pons_analysis.presentation.report import charts
    from pons_analysis.presentation.report.styles import STYLES

    names = set(re.findall(r"var\(--([a-z0-9-]+)\)", inspect.getsource(charts)))
    assert names
    for name in names:
        assert f"--{name}:" in STYLES


def test_report_loader_rejects_non_object_json(tmp_path) -> None:
    from pons_analysis.core.errors import InvariantError
    from pons_analysis.presentation.report.loader import read_json_artifact

    store = ArtifactStore(tmp_path)
    store.write_json("analysis/summary.json", [])
    with pytest.raises(InvariantError):
        read_json_artifact(store, "analysis/summary.json", "test")
