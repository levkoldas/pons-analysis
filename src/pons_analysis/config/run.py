"""Explicit runtime configuration for library sessions.

The library never reads the environment or the current working directory on
import. Callers construct a :class:`RunConfig`; the optional CLI has its own
environment adapter.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from pons_analysis._version import __version__


class CachePolicy(StrEnum):
    """Provider cache behavior for a session."""

    ONLINE = "online"
    OFFLINE = "offline"
    REFRESH = "refresh"

    @property
    def is_offline(self) -> bool:
        return self is CachePolicy.OFFLINE

    @property
    def is_refresh(self) -> bool:
        return self is CachePolicy.REFRESH


@dataclass(frozen=True, slots=True)
class RunConfig:
    """Network, cache, concurrency, and persistence settings."""

    cache: CachePolicy | str = CachePolicy.ONLINE
    persist: bool = False
    timeout: float = 30.0
    connect_timeout: float = 10.0
    max_connections: int = 20
    retries: int = 6
    max_workers: int = 8
    user_agent: str = f"pons-analysis/{__version__}"
    rpc_endpoints: tuple[str, ...] = ()
    gmgn_base: str = "https://openapi.gmgn.ai"
    blockscout_base: str = "https://api.blockscout.com"
    blockscout_pro: bool = True
    headers: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "cache", CachePolicy(self.cache))
        if self.timeout <= 0 or self.connect_timeout <= 0:
            raise ValueError("timeouts must be positive")
        if self.max_connections <= 0 or self.max_workers <= 0:
            raise ValueError("connection and worker counts must be positive")
        if not 1 <= self.retries <= 20:
            raise ValueError("retries must be between 1 and 20")
        if any(
            not endpoint.startswith(("http://", "https://"))
            for endpoint in self.rpc_endpoints
        ):
            raise ValueError("RPC endpoints must be HTTP(S) URLs")
        if any(not key or not value for key, value in self.headers):
            raise ValueError("headers must contain non-empty names and values")

    @property
    def cache_policy(self) -> CachePolicy:
        return CachePolicy(self.cache)

    @property
    def offline(self) -> bool:
        return self.cache_policy.is_offline

    @property
    def refresh(self) -> bool:
        return self.cache_policy.is_refresh
