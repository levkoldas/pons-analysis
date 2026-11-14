"""Errors with stable, credential-free messages."""


class PonsError(RuntimeError):
    """Base class for every expected failure."""


class ConfigurationError(PonsError):
    """The workspace, profile, or credentials are unusable."""


class CacheMiss(PonsError):
    """Offline mode has no matching cached observation."""


class ProviderError(PonsError):
    """A provider returned an unusable response."""


class RetryableError(ProviderError):
    """A transient failure that the retry policy may repeat."""

    def __init__(self, message, *, retry_after=None):
        self.retry_after = retry_after
        super().__init__(message)


class RpcError(ProviderError):
    def __init__(self, method, code, message, data=None):
        self.method = method
        self.code = code
        self.message = str(message)
        self.data = data
        super().__init__(f"{method}: RPC {code}: {self.message}")


class InvariantError(PonsError):
    """Captured evidence violates an accounting or protocol invariant."""


class ResolutionError(PonsError):
    """A token launch cannot be resolved from on-chain metadata."""


class OptionalDependencyError(PonsError):
    """An optional integration was requested without its extra installed."""


class IncompleteHistory(PonsError):
    def __init__(self, result):
        self.result = result
        super().__init__(f"History incomplete after {result['pages']} pages")
