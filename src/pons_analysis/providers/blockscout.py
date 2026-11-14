"""Blockscout Pro/public API with authenticated, cached pagination."""

from typing import Any

from pons_analysis.config import CachePolicy, RunConfig
from pons_analysis.core.errors import CacheMiss, IncompleteHistory, ProviderError
from pons_analysis.credentials import Credentials
from pons_analysis.providers.http import HttpClient
from pons_analysis.providers.pagination import paginate
from pons_analysis.storage.store import ArtifactStore


def _success(data: Any) -> bool:
    if not isinstance(data, (dict, list)):
        return False
    if isinstance(data, dict) and (
        data.get("error")
        or (
            data.get("status") == "0" and data.get("message") != "No transactions found"
        )
    ):
        return False
    return True


class BlockscoutProvider:
    def __init__(
        self,
        http: HttpClient,
        store: ArtifactStore,
        config: RunConfig,
        credentials: Credentials,
        *,
        chain_id: int,
        cache_policy: CachePolicy = CachePolicy.ONLINE,
    ):
        self.http = http
        self.store = store
        self.config = config
        self.credentials = credentials
        self.chain_id = chain_id
        self.cache_policy = cache_policy
        self.base = config.blockscout_base.rstrip("/")
        self.pro = config.blockscout_pro

    @property
    def offline(self) -> bool:
        return self.cache_policy.is_offline

    def _url(self, path: str) -> str:
        if not path.startswith("/") or path.startswith("//") or "?" in path:
            raise ValueError("Blockscout path must be absolute without a query string")
        base = self.base + (f"/{self.chain_id}" if self.pro else "")
        return base + path

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        refresh: bool = False,
    ) -> Any:
        params = dict(params or {})
        refresh = refresh or self.cache_policy.is_refresh
        request = {
            "chain_id": self.chain_id,
            "path": path,
            "params": params,
            "pro": self.pro,
        }
        if not refresh:
            record = self.store.read_cache("blockscout", request)
            if record is not None and _success(record.response):
                return record.response
        if self.offline:
            raise CacheMiss(f"No cached Blockscout response for {path}")
        key = (
            self.credentials.require("blockscout")
            if self.pro
            else self.credentials.get("blockscout")
        )
        headers = {"Authorization": f"Bearer {key}"} if self.pro and key else {}
        query = {} if self.pro else ({"apikey": key} if key else {})
        data = self.http.request(
            "GET", self._url(path), params={**params, **query}, headers=headers
        ).data
        if not _success(data):
            raise ProviderError("Blockscout rejected the request")
        self.store.write_cache(
            "blockscout", request, data, source="blockscout", chain_id=self.chain_id
        )
        return data

    def pages(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        cap: int = 100,
        refresh: bool = False,
        stop=None,
    ):
        return paginate(
            lambda cursor, _: self.get(path, cursor, refresh=refresh),
            params,
            cap=cap,
            stop=stop,
        )

    def all_pages(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        cap: int = 25,
        refresh: bool = False,
    ) -> list[Any]:
        result = self.pages(path, params, cap=cap, refresh=refresh)
        if not result.complete:
            raise IncompleteHistory(result.model_dump())
        return result.items

    def creation_block(self, address: str) -> int:
        """Deployment block for a contract, from the address creation record."""

        info = self.get(f"/api/v2/addresses/{address.lower()}")
        if not isinstance(info, dict):
            raise ProviderError("Blockscout address response is not an object")
        tx_hash = info.get("creation_transaction_hash")
        if not tx_hash:
            raise ProviderError("Blockscout address has no creation transaction")
        transaction = self.get(f"/api/v2/transactions/{tx_hash}")
        if not isinstance(transaction, dict):
            raise ProviderError("Blockscout transaction response is not an object")
        block = transaction.get("block_number")
        if block is None:
            raise ProviderError("Blockscout creation transaction has no block number")
        return int(block, 16) if isinstance(block, str) else int(block)

    def address_transactions(
        self, address: str, *, cap: int = 100, refresh: bool = False, stop=None
    ):
        """Paged native and contract transactions for one address."""
        return self.pages(
            f"/api/v2/addresses/{address.lower()}/transactions",
            {"limit": 50},
            cap=cap,
            refresh=refresh,
            stop=stop,
        )

    def address_internal_transfers(
        self, address: str, *, cap: int = 100, refresh: bool = False, stop=None
    ):
        """Paged internal native transfers for one address."""
        return self.pages(
            f"/api/v2/addresses/{address.lower()}/internal-transactions",
            {"limit": 50},
            cap=cap,
            refresh=refresh,
            stop=stop,
        )
