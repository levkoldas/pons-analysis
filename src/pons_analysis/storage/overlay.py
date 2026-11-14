"""Transient analysis overlay used when persistence is disabled.

Raw evidence and provider caches are read from the real workspace, while every
derived write lands in a temporary directory. Derived analysis reads never fall
back to stale ``analysis/`` files in the base workspace.
"""

from pathlib import Path
from typing import Any

from pons_analysis.storage.store import ArtifactStore


class OverlayStore(ArtifactStore):
    def __init__(
        self,
        base: ArtifactStore,
        root: str | Path,
        *,
        fallback_analysis: bool = False,
    ):
        super().__init__(root)
        self.base = base
        self.fallback_analysis = fallback_analysis

    def _fallback(self, relative: str | Path) -> bool:
        if self.fallback_analysis:
            return True
        return Path(relative).parts[:1] != ("analysis",)

    def exists(self, relative: str | Path) -> bool:
        if super().exists(relative):
            return True
        return self._fallback(relative) and self.base.exists(relative)

    def is_dir(self, relative: str | Path) -> bool:
        if super().is_dir(relative):
            return True
        return self._fallback(relative) and self.base.is_dir(relative)

    def directories(self, relative: str | Path) -> list[str]:
        names = set(super().directories(relative))
        if self._fallback(relative):
            names |= set(self.base.directories(relative))
        return sorted(names)

    def read_json(self, relative: str | Path, *, model=None):
        if super().exists(relative):
            return super().read_json(relative, model=model)
        if not self._fallback(relative):
            return None
        return self.base.read_json(relative, model=model)

    def read_bytes(self, relative: str | Path) -> bytes:
        if super().exists(relative):
            return super().read_bytes(relative)
        if not self._fallback(relative):
            raise FileNotFoundError(relative)
        return self.base.read_bytes(relative)

    def read_csv(self, relative: str | Path) -> list[dict[str, str]]:
        if super().exists(relative):
            return super().read_csv(relative)
        if not self._fallback(relative):
            return []
        return self.base.read_csv(relative)

    def read_cache(self, namespace: str, request: dict[str, Any]):
        if super().exists(super().cache_relative(namespace, request)):
            return super().read_cache(namespace, request)
        return self.base.read_cache(namespace, request)
