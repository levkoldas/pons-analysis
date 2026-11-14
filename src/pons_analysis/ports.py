"""Structural ports used by the library session.

Adapters can be replaced in tests or embedded in another application without
subclassing the concrete providers.
"""

from pathlib import Path
from typing import Any, Protocol

from pons_analysis.core.models import (
    CacheRecord,
    RpcBlock,
    RpcLog,
    RpcReceipt,
    RpcTransaction,
)


class Store(Protocol):
    def path(self, relative: str | Path) -> Path: ...
    def exists(self, relative: str | Path) -> bool: ...
    def is_dir(self, relative: str | Path) -> bool: ...
    def directories(self, relative: str | Path) -> list[str]: ...
    def read_json(self, relative: str | Path, *, model: Any = None) -> Any: ...
    def write_json(self, relative: str | Path, value: Any) -> Any: ...
    def read_bytes(self, relative: str | Path) -> bytes: ...
    def read_csv(self, relative: str | Path) -> list[dict[str, str]]: ...
    def write_csv(
        self,
        relative: str | Path,
        rows: list[dict[str, Any]],
        fields: list[str] | None = None,
    ) -> None: ...
    def write_bytes(self, relative: str | Path, payload: bytes) -> Path: ...
    def read_cache(
        self, namespace: str, request: dict[str, Any]
    ) -> CacheRecord | None: ...
    def write_cache(
        self,
        namespace: str,
        request: dict[str, Any],
        response: Any,
        *,
        source: str,
        chain_id: int | None = None,
    ) -> CacheRecord: ...
    def manifest(self) -> dict[str, Any]: ...


class Rpc(Protocol):
    chain_id: int

    def call(
        self,
        method: str,
        params: list[Any] | None = None,
        *,
        refresh: bool = False,
        cache: bool = True,
    ) -> Any: ...
    def block(self, number: int, *, full: bool = False) -> RpcBlock: ...
    def latest_block(self) -> int: ...
    def transaction(self, tx_hash: str) -> RpcTransaction: ...
    def receipt(self, tx_hash: str) -> RpcReceipt: ...
    def code(self, address: str, block: int | str = "latest") -> str: ...
    def call_contract(
        self,
        address: str,
        signature: str | None = None,
        args: str = "",
        block: int | str = "latest",
        *,
        data: str | None = None,
    ) -> str: ...
    def logs(
        self,
        address: str,
        from_block: int,
        to_block: int,
        topics: list[Any] | None = None,
        *,
        max_results: int = 10_000,
    ) -> list[RpcLog]: ...
    def first_log(
        self,
        address: str,
        from_block: int,
        to_block: int,
        topics: list[Any] | None = None,
        *,
        initial_width: int = 2_000,
        max_width: int = 500_000,
    ) -> RpcLog | None: ...
    def creation_block(
        self, address: str, lo: int = 0, hi: int | None = None
    ) -> int: ...
    def find_block_by_timestamp(
        self, timestamp: int, lo: int = 0, hi: int | None = None
    ) -> int: ...
