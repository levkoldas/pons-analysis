"""Deterministic standalone HTML report over derived analysis artifacts.

The report is a pure renderer: it reads existing ``analysis/`` documents and
never touches raw evidence or provider caches. Output is one self-contained
HTML file with embedded CSS and an inline SVG price/volume chart, plus a stable
JSON bundle and SHA-256 hashes of every source artifact. No external assets,
scripts, fonts, or network access are used.
"""

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pons_analysis.core.constants import REPORT_SCHEMA_VERSION as SCHEMA_VERSION
from pons_analysis.core.errors import ConfigurationError, InvariantError
from pons_analysis.core.models import Launch
from pons_analysis.presentation.report.build import render_html
from pons_analysis.presentation.report.loader import load_report_data
from pons_analysis.storage.store import ArtifactStore

__all__ = ["SCHEMA_VERSION", "render_report"]


def render_report(
    store: ArtifactStore,
    profile: Launch,
    *,
    minutes: int,
    cohort: Iterable[str] = (),
    output: str | Path = "analysis/report.html",
) -> dict[str, Any]:
    """Build a deterministic HTML/JSON report from existing analysis artifacts."""
    if minutes < 1:
        raise ValueError("Report window must be positive")
    out = Path(os.path.normpath(output))
    if out.is_absolute():
        raise InvariantError("Report output must stay inside the workspace")
    if out.suffix.lower() != ".html":
        raise InvariantError("Report output must use the .html extension")
    if out.parts[:1] != ("analysis",):
        raise InvariantError("Report output must stay inside analysis/")
    json_out = out.with_suffix(".json")

    data, sources = load_report_data(store, profile, minutes=minutes, cohort=cohort)
    if str(out) in sources or str(json_out) in sources:
        raise InvariantError("Report output would overwrite a source artifact")
    if store.exists(json_out):
        try:
            existing = store.read_json(json_out)
        except ConfigurationError as exc:
            raise InvariantError(
                "Report JSON destination is not a readable report"
            ) from exc
        if not (
            isinstance(existing, dict)
            and "schema_version" in existing
            and isinstance(existing.get("sources"), dict)
            and isinstance(existing.get("artifacts"), dict)
        ):
            raise InvariantError(
                "Report JSON destination would overwrite a non-report artifact"
            )
    data["artifacts"] = {
        "html": str(out),
        "json": str(json_out),
    }
    html_bytes = render_html(data, sources)
    store.write_bytes(out, html_bytes)
    store.write_json(json_out, data)
    return data
