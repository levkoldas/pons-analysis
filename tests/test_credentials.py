import json

import pytest

from pons_analysis import ConfigurationError, Credentials, RunConfig


def test_repr_hides_keys() -> None:
    credentials = Credentials(
        gmgn_api_key="gmgn-secret", blockscout_api_key="bs-secret"
    )
    text = repr(credentials)
    assert "gmgn-secret" not in text
    assert "bs-secret" not in text
    assert credentials.require("gmgn") == "gmgn-secret"


def test_from_env(monkeypatch) -> None:
    monkeypatch.setenv("GMGN_API_KEY", "one")
    monkeypatch.setenv("BLOCKSCOUT_API_KEY", "two")
    credentials = Credentials.from_env()
    assert credentials.get("gmgn") == "one"
    assert credentials.get("blockscout") == "two"


def test_from_json_file(tmp_path) -> None:
    path = tmp_path / "credentials.json"
    path.write_text(
        json.dumps({"gmgn_api_key": "g", "blockscout": "b"}), encoding="utf-8"
    )
    credentials = Credentials.from_file(path)
    assert credentials.get("gmgn") == "g"
    assert credentials.get("blockscout") == "b"


def test_from_legacy_key_file(tmp_path) -> None:
    path = tmp_path / "key.txt"
    path.write_text("gmgn_api_key: abc\n", encoding="utf-8")
    credentials = Credentials.from_file(path)
    assert credentials.get("gmgn") == "abc"
    assert credentials.get("blockscout") is None


def test_single_line_key_file_with_trailing_newline(tmp_path) -> None:
    path = tmp_path / "key.txt"
    path.write_text("abc123\n", encoding="utf-8")
    assert Credentials.from_file(path).get("gmgn") == "abc123"


def test_blockscout_only_line_is_not_treated_as_gmgn_key(tmp_path) -> None:
    path = tmp_path / "key.txt"
    path.write_text("BLOCKSCOUT_API_KEY=bs-secret", encoding="utf-8")
    credentials = Credentials.from_file(path)
    assert credentials.get("gmgn") is None
    assert credentials.get("blockscout") == "bs-secret"


def test_utf8_bom_json_credentials(tmp_path) -> None:
    path = tmp_path / "credentials.json"
    path.write_text("\ufeff" + json.dumps({"gmgn_api_key": "g"}), encoding="utf-8")
    assert Credentials.from_file(path).get("gmgn") == "g"


def test_missing_key_is_explicit() -> None:
    with pytest.raises(ConfigurationError, match="GMGN_API_KEY"):
        Credentials().require("gmgn")


def test_run_config_validation() -> None:
    with pytest.raises(ValueError):
        RunConfig(timeout=0)
    with pytest.raises(ValueError):
        RunConfig(retries=0)
    with pytest.raises(ValueError):
        RunConfig(rpc_endpoints=("ftp://example",))
    with pytest.raises(ValueError):
        RunConfig(rpc_endpoints=("httpfoo",))
    assert RunConfig(cache="offline").offline is True
    assert RunConfig(cache="refresh").refresh is True
