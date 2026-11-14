"""Atomic, file-based artifacts and content-addressed provider caches.

Every persisted document is a UTF-8 file under one workspace root. Writes are
fsynced and replaced atomically, so a reader sees either the previous complete
document or the new one. Provider caches are keyed by a SHA-256 of the full
canonical request, not by a caller-supplied label.
"""

import csv
import hashlib
import io
import os
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import orjson

from pons_analysis.core.errors import ConfigurationError
from pons_analysis.core.models import CacheRecord

JSON_OPTIONS = orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2
COMPACT_OPTIONS = orjson.OPT_SORT_KEYS


INT64_MIN, INT64_MAX = -(2**63), 2**63 - 1


def _normalize(value: Any) -> Any:
    """Convert models and out-of-range integers into JSON-safe values.

    orjson rejects integers above 64 bits. Wei amounts routinely exceed that,
    so they are stored as decimal strings; Pydantic coerces them back to ints
    when a model is loaded.
    """
    if hasattr(value, "model_dump"):
        return _normalize(value.model_dump(mode="json", by_alias=True))
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_normalize(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, int) and not INT64_MIN <= value <= INT64_MAX:
        return str(value)
    return value


def canonical(value: Any) -> bytes:
    return orjson.dumps(_normalize(value), option=orjson.OPT_SORT_KEYS)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def dumps(value: Any, *, pretty: bool = True) -> bytes:
    return orjson.dumps(
        _normalize(value), option=JSON_OPTIONS if pretty else COMPACT_OPTIONS
    )


class ArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, relative: str | Path) -> Path:
        relative = Path(relative)
        if relative.is_absolute() or ".." in relative.parts:
            raise ConfigurationError("Artifact path must stay inside the workspace")
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ConfigurationError("Artifact path must stay inside the workspace")
        return path

    def exists(self, relative: str | Path) -> bool:
        return self.path(relative).exists()

    def is_dir(self, relative: str | Path) -> bool:
        return self.path(relative).is_dir()

    def directories(self, relative: str | Path) -> list[str]:
        path = self.path(relative)
        if not path.is_dir():
            return []
        return sorted(item.name for item in path.iterdir() if item.is_dir())

    def read_json(self, relative: str | Path, *, model=None):
        path = self.path(relative)
        try:
            payload = orjson.loads(path.read_bytes())
        except FileNotFoundError:
            return None
        except orjson.JSONDecodeError as exc:
            raise ConfigurationError(f"Invalid JSON artifact: {relative}") from exc
        return model.model_validate(payload) if model else payload

    def write_json(self, relative: str | Path, value: Any) -> Any:
        self.write_bytes(relative, dumps(value))
        return value

    def read_bytes(self, relative: str | Path) -> bytes:
        return self.path(relative).read_bytes()

    def read_csv(self, relative: str | Path) -> list[dict[str, str]]:
        try:
            with self.path(relative).open(newline="", encoding="utf-8") as stream:
                return list(csv.DictReader(stream))
        except FileNotFoundError:
            return []

    def write_csv(
        self, relative: str | Path, rows: list[dict[str, Any]], fields=None
    ) -> None:
        stream = io.StringIO(newline="")
        fields = list(fields or (rows[0] if rows else []))
        if fields:
            writer = csv.DictWriter(
                stream, fieldnames=fields, lineterminator="\n", extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(rows)
        self.write_bytes(relative, stream.getvalue().encode("utf-8"))

    def write_bytes(self, relative: str | Path, payload: bytes) -> Path:
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
            ) as stream:
                name = stream.name
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
            try:
                directory = os.open(
                    path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                )
            except OSError:
                pass
            else:
                try:
                    try:
                        os.fsync(directory)
                    except OSError:
                        pass
                finally:
                    os.close(directory)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)
        return path

    # ---- content-addressed provider caches ---------------------------------

    def cache_key(self, request: dict[str, Any]) -> str:
        return digest(request)

    def cache_relative(self, namespace: str, request: dict[str, Any]) -> Path:
        return Path("cache") / namespace / f"{self.cache_key(request)}.json"

    def read_cache(self, namespace: str, request: dict[str, Any]):
        relative = self.cache_relative(namespace, request)
        record = self.read_json(relative, model=CacheRecord)
        if record is None:
            return None
        if canonical(record.request) != canonical(request):
            raise ConfigurationError(f"Cache record request mismatch: {relative}")
        return record

    def write_cache(
        self,
        namespace: str,
        request: dict[str, Any],
        response: Any,
        *,
        source: str,
        chain_id: int | None = None,
    ) -> CacheRecord:
        record = CacheRecord(
            request=_normalize(request),
            response=response,
            source=source,
            chain_id=chain_id,
            retrieved_at=time.time(),
            sha256="0x" + self.cache_key(request),
        )
        self.write_bytes(
            self.cache_relative(namespace, request), dumps(record, pretty=False)
        )
        return record

    def clear_cache(self, namespace: str | None = None) -> int:
        root = self.path(Path("cache") / namespace) if namespace else self.path("cache")
        if not root.exists():
            return 0
        removed = sum(1 for path in root.rglob("*.json") if path.is_file())
        for path in sorted(root.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        return removed

    # ---- evidence manifests ------------------------------------------------

    def manifest(self) -> dict[str, Any]:
        files = {}
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.name == "manifest.json":
                continue
            payload = path.read_bytes()
            files[str(path.relative_to(self.root))] = {
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        return {
            "root": self.root.name,
            "created_at": time.time(),
            "files": files,
        }

    def write_manifest(self, relative: str | Path = "manifest.json") -> dict[str, Any]:
        manifest = self.manifest()
        self.write_json(relative, manifest)
        return manifest
