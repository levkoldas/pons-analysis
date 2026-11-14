from types import SimpleNamespace

import pytest

from pons_analysis.config import CachePolicy
from pons_analysis.core.errors import ProviderError, RpcError
from pons_analysis.providers.http import _retry_after
from pons_analysis.providers.rpc import RpcProvider, is_moving
from pons_analysis.storage.store import ArtifactStore


class FakeHttp:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def request(self, method, url, **kwargs):
        self.calls += 1
        value = self.results.pop(0) if self.results else self.results
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(data=value)


def provider(store, http, *, policy=CachePolicy.ONLINE):
    return RpcProvider(
        http,
        store,
        endpoints=("https://rpc.example",),
        chain_id=4663,
        cache_policy=policy,
    )


def test_implicit_latest_block_parameter_is_moving() -> None:
    address = "0x" + "11" * 20
    assert is_moving("eth_getBalance", [address])
    assert not is_moving("eth_getBalance", [address, "0x10"])
    assert is_moving("eth_getStorageAt", [address, "0x0"])
    assert not is_moving("eth_getStorageAt", [address, "0x0", "0x10"])


def test_null_receipt_is_not_cached(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    receipt = {
        "transactionHash": "0x" + "22" * 32,
        "status": "0x1",
        "blockNumber": "0x10",
        "transactionIndex": "0x0",
        "from": "0x" + "11" * 20,
        "to": "0x" + "33" * 20,
        "gasUsed": "0x5208",
        "effectiveGasPrice": "0x1",
        "logs": [],
    }
    http = FakeHttp(
        [
            {"jsonrpc": "2.0", "id": 1, "result": None},
            {"jsonrpc": "2.0", "id": 1, "result": receipt},
        ]
    )
    rpc = provider(store, http)
    with pytest.raises(ProviderError):
        rpc.receipt("0x" + "22" * 32)
    assert rpc.receipt("0x" + "22" * 32).block_number == 16
    assert http.calls == 2


def test_offline_log_replay_can_split_cached_leaves(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    address = "0x" + "11" * 20

    def log(block: int) -> dict:
        return {
            "address": address,
            "topics": ["0x" + "44" * 32],
            "data": "0x",
            "blockNumber": hex(block),
            "transactionHash": "0x" + "55" * 32,
            "transactionIndex": "0x0",
            "logIndex": "0x0",
        }

    class LogHttp(FakeHttp):
        def request(self, method, url, **kwargs):
            self.calls += 1
            query = kwargs["json"]["params"][0]
            low = int(query["fromBlock"], 16)
            high = int(query["toBlock"], 16)
            if high - low > 2:
                return SimpleNamespace(
                    data={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "error": {
                            "code": -32005,
                            "message": "query returned more than 10000 results",
                        },
                    }
                )
            return SimpleNamespace(
                data={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": [log(low), log(high)],
                }
            )

    online = provider(store, LogHttp([]))
    assert len(online.logs(address, 0, 4)) == 4
    offline = provider(store, FakeHttp([]), policy=CachePolicy.OFFLINE)
    assert len(offline.logs(address, 0, 4)) == 4


def test_gmgn_rejects_non_read_methods(tmp_path) -> None:
    from pons_analysis.config import RunConfig
    from pons_analysis.credentials import Credentials
    from pons_analysis.providers.gmgn import GmgnProvider

    gmgn = GmgnProvider(
        FakeHttp([]),
        ArtifactStore(tmp_path),
        RunConfig(),
        Credentials(gmgn_api_key="secret"),
        chain="robinhood",
        token="0x" + "11" * 20,
    )
    with pytest.raises(ValueError):
        gmgn._check("DELETE", "/v1/token/info")


def test_cache_roundtrip_with_normalized_request(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    request = {"params": [{"topics": ("0x" + "11" * 32,)}]}
    store.write_cache("rpc", request, [], source="rpc")
    assert store.read_cache("rpc", request) is not None


def test_rate_limit_does_not_trigger_log_bisection(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    http = FakeHttp(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32005, "message": "rate limit exceeded"},
            }
        ]
    )
    rpc = provider(store, http)
    with pytest.raises(RpcError):
        rpc.logs("0x" + "11" * 20, 0, 10)
    assert http.calls == 1


def test_retry_after_rejects_non_finite_values() -> None:
    import httpx

    assert _retry_after(httpx.Headers({"retry-after": "NaN"})) is None
    assert _retry_after(httpx.Headers({"retry-after": "inf"})) is None


class RangeHttp:
    def __init__(self, limit: int):
        self.limit = limit
        self.ranges: list[tuple[int, int]] = []

    def request(self, method, url, **kwargs):
        query = kwargs["json"]["params"][0]
        low = int(query["fromBlock"], 16)
        high = int(query["toBlock"], 16)
        self.ranges.append((low, high))
        if high - low > self.limit:
            raise RpcError("eth_getLogs", -32000, "log query timed out")
        return SimpleNamespace(
            data={
                "jsonrpc": "2.0",
                "id": 1,
                "result": [
                    {
                        "address": "0x" + "11" * 20,
                        "topics": ["0x" + "22" * 32],
                        "data": "0x",
                        "blockNumber": hex(low),
                        "transactionHash": "0x" + "33" * 32,
                        "transactionIndex": "0x0",
                        "logIndex": "0x0",
                    }
                ],
            }
        )


def test_first_log_narrows_a_timing_out_range(tmp_path) -> None:
    http = RangeHttp(limit=100)
    rpc = provider(ArtifactStore(tmp_path), http)
    log = rpc.first_log("0x" + "11" * 20, 0, 1_000)
    assert log is not None
    assert len(http.ranges) > 1
    assert all(
        right - left <= previous[1] - previous[0]
        for previous, (left, right) in zip(http.ranges, http.ranges[1:], strict=False)
    )


class UrlHttp:
    def __init__(self, results):
        self.results = list(results)
        self.urls: list[str] = []

    def request(self, method, url, **kwargs):
        self.urls.append(url)
        value = self.results.pop(0)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(data=value)


def test_rpc_reuses_the_last_successful_endpoint(tmp_path) -> None:
    http = UrlHttp(
        [
            {"jsonrpc": "2.0", "id": 1, "result": "0x10"},
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "number": "0x10",
                    "hash": "0x" + "44" * 32,
                    "parentHash": "0x" + "55" * 32,
                    "timestamp": "0x1",
                },
            },
        ]
    )
    rpc = RpcProvider(
        http,
        ArtifactStore(tmp_path),
        endpoints=("https://first.example", "https://second.example"),
        chain_id=4663,
    )
    assert rpc.latest_block() == 16
    assert rpc.block(16).number == 16
    assert http.urls == ["https://first.example", "https://first.example"]
