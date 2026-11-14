"""Credentials object with explicit sources and redacted representation."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from pons_analysis.core.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class Credentials:
    """API keys supplied explicitly by the caller.

    Values are omitted from ``repr`` so accidental logging cannot leak them.
    Empty credentials are valid for public RPC-only sessions.

    The GMGN client is read-only: it sends ``gmgn_api_key`` as ``X-APIKEY``.
    GMGN's ed25519 public key belongs to its signed write routes and is
    intentionally not parsed here.
    """

    gmgn_api_key: str | None = field(default=None, repr=False)
    blockscout_api_key: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Credentials:
        values = os.environ if env is None else env
        return cls(
            gmgn_api_key=_clean(values.get("GMGN_API_KEY")),
            blockscout_api_key=_clean(values.get("BLOCKSCOUT_API_KEY")),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> Credentials:
        """Read a JSON credential map or the legacy key-file syntax."""

        source = Path(path).expanduser()
        try:
            text = source.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise ConfigurationError(
                f"Cannot read credential file {source.name}"
            ) from exc
        if text.lstrip().startswith("{"):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ConfigurationError(
                    f"Cannot parse credential file {source.name}"
                ) from exc
            if not isinstance(payload, dict):
                raise ConfigurationError("Credential JSON must be an object")
            return cls(
                gmgn_api_key=_clean(payload.get("gmgn") or payload.get("gmgn_api_key")),
                blockscout_api_key=_clean(
                    payload.get("blockscout") or payload.get("blockscout_api_key")
                ),
            )
        gmgn = _key_file_value(text, "gmgn")
        blockscout = _key_file_value(text, "blockscout")
        stripped = text.strip()
        if (
            gmgn is None
            and blockscout is None
            and stripped
            and not any(c.isspace() for c in stripped)
        ):
            gmgn = stripped
        return cls(gmgn_api_key=gmgn, blockscout_api_key=blockscout)

    def require(self, service: str) -> str:
        value = self.get(service)
        if not value:
            variable = f"{service.upper()}_API_KEY"
            raise ConfigurationError(f"Missing {variable}")
        return value

    def get(self, service: str) -> str | None:
        if service == "gmgn":
            return _clean(self.gmgn_api_key)
        if service == "blockscout":
            return _clean(self.blockscout_api_key)
        raise ConfigurationError(f"Unknown credential service {service!r}")


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _key_file_value(text: str, service: str) -> str | None:
    prefix = rf"{re.escape(service)}[\s_-]+"
    match = re.search(
        rf"^\s*(?:export\s+)?{prefix}api[\s_-]*key\s*[:=]\s*(.+)$",
        text,
        re.M | re.I,
    )
    if not match:
        return None
    return match.group(1).strip().strip("\"'")
