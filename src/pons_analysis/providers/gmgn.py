"""Read-only GMGN OpenAPI access with fresh signed request metadata."""

import time
import uuid
from typing import Any

import orjson

from pons_analysis.config import CachePolicy, RunConfig
from pons_analysis.core.errors import CacheMiss, ProviderError, RetryableError
from pons_analysis.credentials import Credentials
from pons_analysis.providers.http import HttpClient, retryer
from pons_analysis.providers.pagination import paginate
from pons_analysis.storage.store import ArtifactStore

READ_PREFIXES = ("/v1/token/", "/v1/market/", "/v1/user/")
READ_POST_PATHS = frozenset({"/v1/user/wallet_profits"})
RESERVED_PARAMS = frozenset({"timestamp", "client_id", "apikey", "api_key"})


class GmgnProvider:
    def __init__(
        self,
        http: HttpClient,
        store: ArtifactStore,
        config: RunConfig,
        credentials: Credentials,
        *,
        chain: str,
        token: str,
        cache_policy: CachePolicy = CachePolicy.ONLINE,
    ):
        self.http = http
        self.store = store
        self.config = config
        self.credentials = credentials
        self.chain = chain
        self.token = token
        self.cache_policy = cache_policy
        self.base = config.gmgn_base.rstrip("/")

    @property
    def offline(self) -> bool:
        return self.cache_policy.is_offline

    def _check(self, path: str, method: str) -> None:
        if method not in {"GET", "POST"}:
            raise ValueError("Only read-only GMGN research endpoints are supported")
        if not path.startswith("/") or path.startswith("//") or "?" in path:
            raise ValueError("GMGN path must be absolute without a query string")
        if not path.startswith(READ_PREFIXES):
            raise ValueError("Only read-only GMGN research endpoints are supported")
        if method == "POST" and path not in READ_POST_PATHS:
            raise ValueError("Only read-only GMGN research endpoints are supported")

    def _fetch(
        self, method: str, path: str, params: dict[str, Any], key: str
    ) -> dict[str, Any]:
        query = {
            "timestamp": int(time.time()),
            "client_id": str(uuid.uuid4()),
        }
        if method == "GET":
            query.update(params)
        response = self.http.request(
            method,
            self.base + path,
            params=query,
            headers={"X-APIKEY": key},
            json=params if method == "POST" else None,
        )
        payload = response.data
        if not isinstance(payload, dict):
            raise ProviderError("Expected a GMGN response object")
        code = payload.get("code")
        if code in (429, "429"):
            raise RetryableError("GMGN rate limit", retry_after=5)
        if code not in (0, "0", None) or payload.get("error"):
            raise ProviderError("GMGN rejected the request")
        return orjson.loads(orjson.dumps(payload).replace(key.encode(), b"[REDACTED]"))

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        refresh: bool = False,
    ) -> Any:
        self._check(path, method)
        params = dict(params or {})
        if RESERVED_PARAMS & params.keys():
            raise ValueError("Authentication parameters are managed by the client")
        request = {"path": path, "method": method, "params": params}
        refresh = refresh or self.cache_policy.is_refresh
        if not refresh:
            record = self.store.read_cache("gmgn", request)
            if record is not None:
                return record.response
        if self.offline:
            raise CacheMiss(f"No cached GMGN response for {path}")
        key = self.credentials.require("gmgn")
        for attempt in retryer(self.config.retries):
            with attempt:
                payload = self._fetch(method, path, params, key)
        data = payload.get("data", payload)
        self.store.write_cache("gmgn", request, data, source="gmgn")
        return data

    def get(self, path: str, params: dict[str, Any] | None = None, **kwargs) -> Any:
        return self.request("GET", path, params, **kwargs)

    def post(self, path: str, body: dict[str, Any], **kwargs) -> Any:
        return self.request("POST", path, body, **kwargs)

    def token_info(self, **kwargs) -> Any:
        return self.get(
            "/v1/token/info",
            {"chain": self.chain, "address": self.token},
            **kwargs,
        )

    def wallet_activity(
        self, address: str, *, limit: int = 100, cap: int = 100, **kwargs
    ):
        return paginate(
            lambda cursor, _: self.get(
                "/v1/user/wallet_activity",
                {
                    "chain": self.chain,
                    "wallet_address": address,
                    "limit": limit,
                    **cursor,
                },
                **kwargs,
            ),
            cap=cap,
            items_key="activities",
            cursor_key="next",
        )

    def wallet_token_balance(self, address: str, **kwargs) -> Any:
        return self.get(
            "/v1/user/wallet_token_balance",
            {
                "chain": self.chain,
                "wallet_address": address,
                "token_address": self.token,
            },
            **kwargs,
        )

    def wallet_profits(
        self, addresses: list[str], *, chain: str | None = None, **kwargs
    ) -> Any:
        return self.post(
            "/v1/user/wallet_profits",
            {"chain": chain or self.chain, "wallet_addresses": addresses},
            **kwargs,
        )
