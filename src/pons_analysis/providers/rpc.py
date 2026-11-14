"""Read-only EVM JSON-RPC with request identity, batching, and cache safety."""

from collections.abc import Iterable
from typing import Any

from pons_analysis.config import CachePolicy
from pons_analysis.core.errors import CacheMiss, ProviderError, RpcError
from pons_analysis.core.evm import position, selector
from pons_analysis.core.models import RpcBlock, RpcLog, RpcReceipt, RpcTransaction
from pons_analysis.providers.http import HttpClient
from pons_analysis.storage.store import ArtifactStore

MOVING_TAGS = frozenset({"latest", "pending", "safe", "finalized"})
ALWAYS_MOVING = frozenset(
    {
        "eth_blockNumber",
        "eth_gasPrice",
        "eth_maxPriorityFeePerGas",
        "eth_syncing",
        "net_peerCount",
        "net_listening",
        "eth_feeHistory",
    }
)
READ_METHODS = frozenset(
    {
        "eth_call",
        "eth_estimateGas",
        "eth_chainId",
        "eth_getBalance",
        "eth_getCode",
        "eth_getStorageAt",
        "eth_getTransactionCount",
        "eth_getBlockByNumber",
        "eth_getBlockByHash",
        "eth_getBlockReceipts",
        "eth_getTransactionByHash",
        "eth_getTransactionReceipt",
        "eth_getLogs",
        "eth_blockNumber",
        "eth_gasPrice",
        "eth_feeHistory",
        "eth_maxPriorityFeePerGas",
        "eth_syncing",
        "web3_clientVersion",
        "net_version",
        "net_peerCount",
        "net_listening",
    }
)


def _moving(value: Any) -> bool:
    if isinstance(value, str):
        return value in MOVING_TAGS
    if isinstance(value, dict):
        return any(_moving(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_moving(item) for item in value)
    return False


def is_moving(method: str, params: list[Any]) -> bool:
    if method in ALWAYS_MOVING or _moving(params):
        return True
    if method == "eth_getLogs":
        query = params[0] if params else {}
        return not query.get("blockHash") and (
            "fromBlock" not in query or "toBlock" not in query
        )
    default_block_methods = {
        "eth_call": 2,
        "eth_estimateGas": 2,
        "eth_getBalance": 2,
        "eth_getCode": 2,
        "eth_getTransactionCount": 2,
        "eth_getStorageAt": 3,
    }
    required = default_block_methods.get(method)
    if required is not None and len(params) < required:
        return True
    return False


def _log_limit_error(error: RpcError) -> bool:
    message = error.message.lower()
    if any(
        text in message
        for text in (
            "rate limit",
            "too many requests",
            "daily request limit",
        )
    ):
        return False
    return any(
        text in message
        for text in (
            "too many results",
            "more than",
            "response size",
            "range too",
            "range exceeds",
            "spans",
            "block range",
            "exceed maximum block range",
            "timeout",
            "timed out",
            "time out",
        )
    )


class RpcProvider:
    def __init__(
        self,
        http: HttpClient,
        store: ArtifactStore,
        *,
        endpoints: Iterable[str],
        chain_id: int,
        cache_policy: CachePolicy = CachePolicy.ONLINE,
    ):
        self.http = http
        self.store = store
        self.endpoints = tuple(endpoints)
        if not self.endpoints:
            raise ValueError("At least one RPC endpoint is required")
        self.chain_id = chain_id
        self.cache_policy = cache_policy
        self._active = 0

    @property
    def offline(self) -> bool:
        return self.cache_policy.is_offline

    # ---- transport ---------------------------------------------------------

    def _unavailable(self, error: RpcError) -> bool:
        return error.code == -32601 or any(
            marker in error.message.lower()
            for marker in (
                "historical state",
                "archive",
                "missing trie node",
                "header not found",
                "unsupported block",
                "is not available",
                "pruned",
            )
        )

    def _send(self, payload: Any, validate=None) -> Any:
        last: Exception | None = None
        order = [self._active] + [
            index for index in range(len(self.endpoints)) if index != self._active
        ]
        for index in order:
            endpoint = self.endpoints[index]
            try:
                data = self.http.request("POST", endpoint, json=payload).data
                result = validate(data) if validate else data
                self._active = index
                return result
            except RpcError as exc:
                if not self._unavailable(exc):
                    raise
                last = exc
            except ProviderError as exc:
                last = exc
        detail = f": {last}" if last is not None else ""
        raise ProviderError(
            "No RPC endpoint served the request; the method or historical state "
            f"may be unavailable{detail}"
        ) from last

    @staticmethod
    def _validate_one(data: Any, method: str, request_id: int) -> Any:
        if (
            not isinstance(data, dict)
            or data.get("jsonrpc") != "2.0"
            or type(data.get("id")) is not type(request_id)
            or data.get("id") != request_id
            or ("result" in data) == ("error" in data)
        ):
            raise ProviderError(f"Malformed JSON-RPC response for {method}")
        if "error" in data:
            error = data["error"]
            if not isinstance(error, dict):
                raise ProviderError(f"Malformed JSON-RPC error for {method}")
            raise RpcError(
                method,
                error.get("code"),
                error.get("message", "request failed"),
                error.get("data"),
            )
        return data["result"]

    # ---- public calls ------------------------------------------------------

    def call(
        self,
        method: str,
        params: list[Any] | None = None,
        *,
        refresh: bool = False,
        cache: bool = True,
    ) -> Any:
        if method not in READ_METHODS:
            raise ValueError(f"Unsupported read-only RPC method: {method}")
        params = list(params or [])
        refresh = refresh or self.cache_policy.is_refresh
        stable = cache and not is_moving(method, params)
        request = {"chain_id": self.chain_id, "method": method, "params": params}
        if stable and not refresh:
            record = self.store.read_cache("rpc", request)
            if record is not None:
                return record.response
        if self.offline:
            raise CacheMiss(f"No cached RPC response for {method}")
        result = self._send(
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            lambda data: self._validate_one(data, method, 1),
        )
        if stable and result is not None:
            self.store.write_cache(
                "rpc", request, result, source="rpc", chain_id=self.chain_id
            )
        return result

    def call_many(
        self,
        calls: list[tuple[str, list[Any]]],
        *,
        refresh: bool = False,
        cache: bool = True,
    ) -> list[Any]:
        if not calls:
            return []
        for method, _ in calls:
            if method not in READ_METHODS:
                raise ValueError(f"Unsupported read-only RPC method: {method}")
        refresh = refresh or self.cache_policy.is_refresh
        stable = cache and not any(is_moving(m, p) for m, p in calls)
        request = {
            "chain_id": self.chain_id,
            "batch": [{"method": m, "params": p} for m, p in calls],
        }
        if stable and not refresh:
            record = self.store.read_cache("rpc", request)
            if record is not None:
                return record.response
        if self.offline:
            raise CacheMiss("No cached RPC batch response")
        body = [
            {"jsonrpc": "2.0", "id": i, "method": method, "params": params}
            for i, (method, params) in enumerate(calls)
        ]

        def validate_batch(data):
            if not isinstance(data, list) or len(data) != len(calls):
                raise ProviderError("Missing JSON-RPC batch responses")
            indexed = {}
            for row in data:
                if (
                    not isinstance(row, dict)
                    or type(row.get("id")) is not int
                    or row["id"] not in range(len(calls))
                    or row["id"] in indexed
                ):
                    raise ProviderError("Invalid or duplicate JSON-RPC batch id")
                indexed[row["id"]] = row
            return [
                self._validate_one(indexed[i], method, i)
                for i, (method, _) in enumerate(calls)
            ]

        results = self._send(body, validate_batch)
        if stable and all(row is not None for row in results):
            self.store.write_cache(
                "rpc", request, results, source="rpc", chain_id=self.chain_id
            )
        return results

    # ---- typed reads -------------------------------------------------------

    def block(self, number: int, *, full: bool = False) -> RpcBlock:
        result = self.call("eth_getBlockByNumber", [hex(number), full])
        if not result:
            raise ProviderError(f"Block {number} is unavailable")
        return RpcBlock.model_validate(result)

    def latest_block(self) -> int:
        return int(self.call("eth_blockNumber", []), 16)

    def transaction(self, tx_hash: str) -> RpcTransaction:
        result = self.call("eth_getTransactionByHash", [tx_hash])
        if not result:
            raise ProviderError(f"Transaction {tx_hash} is unavailable")
        return RpcTransaction.model_validate(result)

    def receipt(self, tx_hash: str) -> RpcReceipt:
        result = self.call("eth_getTransactionReceipt", [tx_hash])
        if not result:
            raise ProviderError(f"Receipt {tx_hash} is unavailable")
        return RpcReceipt.model_validate(result)

    def balance(self, address: str, block: int | str = "latest") -> int:
        tag = block if isinstance(block, str) else hex(block)
        return int(self.call("eth_getBalance", [address, tag]), 16)

    def transaction_count(self, address: str, block: int | str = "latest") -> int:
        tag = block if isinstance(block, str) else hex(block)
        return int(self.call("eth_getTransactionCount", [address, tag]), 16)

    def code(self, address: str, block: int | str = "latest") -> str:
        tag = block if isinstance(block, str) else hex(block)
        return self.call("eth_getCode", [address, tag])

    def call_contract(
        self,
        address: str,
        signature: str | None = None,
        args: str = "",
        block: int | str = "latest",
        *,
        data: str | None = None,
    ) -> str:
        tag = block if isinstance(block, str) else hex(block)
        payload = data if data is not None else selector(signature or "") + args
        return self.call("eth_call", [{"to": address, "data": payload}, tag])

    def logs(
        self,
        address: str,
        from_block: int,
        to_block: int,
        topics: list[Any] | None = None,
        *,
        max_results: int = 10_000,
    ) -> list[RpcLog]:
        if from_block < 0 or to_block < from_block:
            raise ValueError("Invalid inclusive block range")
        query: dict[str, Any] = {
            "address": address,
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
        }
        if topics is not None:
            query["topics"] = topics
        try:
            raw = self.call("eth_getLogs", [query])
            if not isinstance(raw, list):
                raise ProviderError("Expected an RPC log array")
            if len(raw) < max_results:
                return [
                    RpcLog.model_validate(item) for item in sorted(raw, key=position)
                ]
        except CacheMiss:
            if from_block == to_block:
                raise
        except RpcError as exc:
            if not _log_limit_error(exc):
                raise
        if from_block == to_block:
            raise ProviderError(
                "Provider log limit reached in a single block; coverage is incomplete"
            )
        middle = (from_block + to_block) // 2
        return self.logs(
            address, from_block, middle, topics, max_results=max_results
        ) + self.logs(address, middle + 1, to_block, topics, max_results=max_results)

    def first_log(
        self,
        address: str,
        from_block: int,
        to_block: int,
        topics: list[Any] | None = None,
        *,
        initial_width: int = 2_000,
        max_width: int = 500_000,
    ) -> RpcLog | None:
        """First matching log, scanning forward with adaptive range widths."""

        if from_block < 0 or to_block < from_block:
            raise ValueError("Invalid inclusive block range")
        if initial_width < 1 or max_width < initial_width:
            raise ValueError("Invalid log scan widths")
        low = from_block
        width = initial_width
        while low <= to_block:
            high = min(low + width - 1, to_block)
            query: dict[str, Any] = {
                "address": address,
                "fromBlock": hex(low),
                "toBlock": hex(high),
            }
            if topics is not None:
                query["topics"] = topics
            try:
                raw = self.call("eth_getLogs", [query])
            except RpcError as exc:
                if width <= 1 or not _log_limit_error(exc):
                    raise
                width = max(1, width // 2)
                continue
            if not isinstance(raw, list):
                raise ProviderError("Expected an RPC log array")
            if raw:
                return min(
                    (RpcLog.model_validate(item) for item in raw),
                    key=position,
                )
            low = high + 1
            width = min(max_width, width * 2)
        return None

    def creation_block(self, address: str, lo: int = 0, hi: int | None = None) -> int:
        """First block where ``eth_getCode`` is non-empty (O(log N) probes)."""
        hi = self.latest_block() if hi is None else hi
        if self.code(address, hi) == "0x":
            raise ProviderError(f"No contract code for {address}")
        while lo < hi:
            mid = (lo + hi) // 2
            if self.code(address, mid) != "0x":
                hi = mid
            else:
                lo = mid + 1
        return lo

    def find_block_by_timestamp(
        self, timestamp: int, lo: int = 0, hi: int | None = None
    ) -> int:
        hi = self.latest_block() if hi is None else hi
        if lo < 0 or hi < lo:
            raise ValueError("Invalid block search bounds")
        if self.block(hi).timestamp < timestamp:
            raise ValueError("Timestamp is newer than the upper search bound")
        while lo < hi:
            mid = (lo + hi) // 2
            if self.block(mid).timestamp >= timestamp:
                hi = mid
            else:
                lo = mid + 1
        return lo
