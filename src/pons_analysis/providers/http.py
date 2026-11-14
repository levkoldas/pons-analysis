"""Pooled HTTP transport with service-aware retries over httpx.

Requests are rebuilt on every attempt so signed GMGN timestamps stay fresh.
Transient statuses and network errors use exponential backoff with jitter;
``Retry-After`` takes precedence when the provider supplies it. Credentials
never appear in exception messages.
"""

import email.utils
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import orjson
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from pons_analysis.config import RunConfig
from pons_analysis.core.errors import ProviderError, RetryableError

TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_backoff = wait_exponential_jitter(multiplier=0.5, max=30, jitter=1)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    data: Any
    headers: httpx.Headers


def _retry_after(headers: httpx.Headers) -> float | None:
    raw = headers.get("retry-after")
    if not raw:
        return None
    raw = raw.strip()
    try:
        value = float(raw)
    except ValueError:
        pass
    else:
        return min(max(value, 0.0), 60.0) if math.isfinite(value) else None
    try:
        when = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return min(max((when - datetime.now(UTC)).total_seconds(), 0.0), 60.0)


def retryer(attempts: int) -> Retrying:
    return Retrying(
        stop=stop_after_attempt(attempts),
        wait=_wait,
        retry=retry_if_exception_type((httpx.TransportError, RetryableError)),
        reraise=True,
    )


def _wait(retry_state) -> float:
    error = retry_state.outcome.exception()
    if isinstance(error, RetryableError) and error.retry_after is not None:
        return error.retry_after
    return _backoff(retry_state)


class HttpClient:
    def __init__(self, config: RunConfig):
        self.config = config
        headers = {
            "User-Agent": config.user_agent,
            "Accept": "application/json",
            **dict(config.headers),
        }
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                config.timeout,
                connect=config.connect_timeout,
                pool=config.connect_timeout,
            ),
            limits=httpx.Limits(
                max_connections=config.max_connections,
                max_keepalive_connections=config.max_connections,
            ),
            follow_redirects=False,
            headers=headers,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        json: Any = None,
        content: bytes | None = None,
        attempts: int | None = None,
    ) -> HttpResponse:
        attempts = attempts or self.config.retries
        for attempt in retryer(attempts):
            with attempt:
                return self._once(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    json=json,
                    content=content,
                )
        raise AssertionError("unreachable")

    def _once(self, method, url, *, params, headers, json, content) -> HttpResponse:
        try:
            response = self._client.request(
                method,
                url,
                params=params,
                headers=headers,
                json=json,
                content=content,
            )
        except httpx.TimeoutException as exc:
            raise RetryableError("HTTP timeout") from exc
        except httpx.TransportError as exc:
            raise RetryableError(
                f"HTTP transport failed: {type(exc).__name__}"
            ) from exc
        if response.status_code in TRANSIENT_STATUS:
            raise RetryableError(
                f"HTTP {response.status_code}",
                retry_after=_retry_after(response.headers),
            )
        if not 200 <= response.status_code < 300:
            detail = response.text.strip().replace("\n", " ")[:240]
            message = f"HTTP {response.status_code} from provider"
            if detail:
                message = f"{message}: {detail}"
            raise ProviderError(message)
        content_type = response.headers.get("content-type", "")
        if "json" in content_type or response.content[:1] in {b"{", b"["}:
            try:
                data = orjson.loads(response.content) if response.content else None
            except orjson.JSONDecodeError as exc:
                raise ProviderError("Provider returned malformed JSON") from exc
        else:
            data = response.content
        return HttpResponse(response.status_code, data, response.headers)

    def get_json(self, url: str, **kwargs) -> Any:
        return self.request("GET", url, **kwargs).data

    def post_json(self, url: str, payload: Any, **kwargs) -> Any:
        kwargs.pop("json", None)
        return self.request("POST", url, json=payload, **kwargs).data
