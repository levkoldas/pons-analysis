import pytest
from typer.testing import CliRunner

from pons_analysis.core.errors import ConfigurationError
from pons_analysis.presentation.cli import app
from pons_analysis.presentation.cli.commands.helpers import _cohort_roots
from pons_analysis.presentation.cli.renderers.market import _candles_tables
from pons_analysis.presentation.cli.renderers.positions import (
    _positions_tables,
    _route_performance_tables,
)
from pons_analysis.presentation.cli.renderers.report import _report_tables
from pons_analysis.presentation.cli.renderers.summary import _summary_tables
from pons_analysis.presentation.cli.renderers.wallets import _wallet_scorecard_tables
from pons_analysis.presentation.cli.runtime import _build_session

runner = CliRunner()


def test_subcommand_help_does_not_require_token() -> None:
    result = runner.invoke(app, ["analyze", "--help"])
    assert result.exit_code == 0
    result = runner.invoke(app, ["analyze", "positions", "--help"])
    assert result.exit_code == 0


def test_command_without_token_fails_with_configuration_error() -> None:
    result = runner.invoke(app, ["manifest"])
    assert result.exit_code == 1
    assert "Missing --token or PONS_TOKEN" in result.output


def test_missing_cohort_file_is_an_error(tmp_path) -> None:
    with pytest.raises(ConfigurationError):
        _cohort_roots(None, [], tmp_path / "missing.json")


def test_cohort_csv_requires_destination_wallet(tmp_path) -> None:
    path = tmp_path / "cohort.csv"
    path.write_text("wallet\n0xabc\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        _cohort_roots(None, [], path)


def test_empty_cohort_file_is_an_error(tmp_path) -> None:
    path = tmp_path / "cohort.csv"
    path.write_text("destination_wallet\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        _cohort_roots(None, [], path)
    path.write_text("", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        _cohort_roots(None, [], path)


def test_invalid_cohort_address_is_an_error() -> None:
    with pytest.raises(ConfigurationError):
        _cohort_roots(None, ["not-an-address"], None)


def test_invalid_launch_input_gets_friendly_error() -> None:
    result = runner.invoke(
        app,
        [
            "--token",
            "not-an-address",
            "--supply",
            "1",
            "--migration-block",
            "1",
            "--start-timestamp",
            "1",
            "profile",
        ],
    )
    assert result.exit_code == 1
    assert "Configuration error" in result.output
    assert "Traceback" not in result.output


def test_candle_renderer_handles_null_metrics(capsys) -> None:
    _candles_tables(
        {
            "profile": "pons",
            "minutes": 30,
            "candles": 1,
            "realized_volatility_bps": None,
            "max_range_bps": None,
            "top_by_volume": [],
        },
        5,
    )
    assert "None" not in capsys.readouterr().out


def test_report_renderer_handles_null_metrics(capsys) -> None:
    _report_tables(
        {
            "artifacts": {
                "html": "analysis/report.html",
                "json": "analysis/report.json",
            },
            "sources": {},
            "trajectory": {"summary": {"reserve_replay": None}},
            "positions": {"summary": {}},
            "cohort": {"terminal_holders": None},
            "clusters": {"clusters": None, "behavior": {"round_trips": None}},
            "fees": {"totals": {"fee_burden_bps": None}},
        }
    )
    assert "None" not in capsys.readouterr().out


def test_summary_renderer_hides_null_scalars(capsys) -> None:
    _summary_tables({"profile": "pons", "migration": None, "migration_seconds": None})
    assert "None" not in capsys.readouterr().out


def test_wallet_scorecard_renderer_handles_unknown_counts(capsys) -> None:
    _wallet_scorecard_tables(
        {
            "wallets": 2,
            "profitable_wallets": None,
            "losing_wallets": None,
            "top_by_net": [],
        },
        5,
        "net",
    )
    assert "None" not in capsys.readouterr().out


def test_route_renderer_handles_unknown_win_loss(capsys) -> None:
    _route_performance_tables(
        {
            "profile": "pons",
            "minutes": 30,
            "top_by_net": [
                {
                    "route_short": "0xabc",
                    "selector": "0x12345678",
                    "wallets": 2,
                    "profitable_wallets": None,
                    "losing_wallets": None,
                    "net_roi_bps": None,
                    "net_quote_eth": None,
                }
            ],
        },
        5,
        "net",
    )
    assert "None" not in capsys.readouterr().out


def test_positions_renderer_handles_null_rankings(capsys) -> None:
    _positions_tables({"profile": "pons", "top_by_net": None}, 5)
    assert "None" not in capsys.readouterr().out


def test_migration_block_requires_explicit_cut_indices(tmp_path) -> None:
    with pytest.raises(ConfigurationError, match="migration-tx-index"):
        _build_session(
            "0x" + "11" * 20,
            workspace=tmp_path,
            offline=False,
            credentials_file=None,
            migration_block=56007631,
            migration_tx_index=None,
            migration_log_index=None,
            start_timestamp=None,
            launch_start_block=None,
            pool_id=None,
            supply=None,
            decimals=None,
        )


def test_start_timestamp_requires_explicit_launch_fields(tmp_path) -> None:
    with pytest.raises(ConfigurationError):
        _build_session(
            "0x" + "11" * 20,
            workspace=tmp_path,
            offline=False,
            credentials_file=None,
            migration_block=None,
            migration_tx_index=0,
            migration_log_index=0,
            start_timestamp=123,
            launch_start_block=None,
            pool_id=None,
            supply=None,
            decimals=None,
        )


def test_invalid_cohort_file_encoding_is_friendly(tmp_path) -> None:
    path = tmp_path / "cohort.csv"
    path.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(ConfigurationError):
        _cohort_roots(None, [], path)
