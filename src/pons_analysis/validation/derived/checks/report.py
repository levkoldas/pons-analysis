"""Standalone report provenance checks."""

import hashlib

from pons_analysis.core.constants import REPORT_SCHEMA_VERSION as SCHEMA_VERSION
from pons_analysis.core.errors import ConfigurationError
from pons_analysis.validation.derived.context import ValidationContext


def _exists(ctx: ValidationContext, path: object) -> bool:
    if not isinstance(path, str):
        return False
    try:
        return ctx.store.exists(path)
    except ConfigurationError:
        return False


def run(ctx: ValidationContext) -> None:
    report = ctx.report
    if report is not None:
        ctx.check(
            "report schema",
            report.get("schema_version") == SCHEMA_VERSION,
            f"{report.get('schema_version')} != {SCHEMA_VERSION}",
        )
        sources = report.get("sources")
        if sources is None:
            sources = {}
        elif not isinstance(sources, dict):
            ctx.check("report sources shape", False, "sources must be an object")
            sources = {}
        missing = [str(path) for path in sources if not _exists(ctx, path)]
        ctx.check("report sources exist", not missing, ", ".join(missing[:5]))
        mismatched = []
        for path, meta in sources.items():
            if not isinstance(path, str) or path in missing:
                continue
            if not isinstance(meta, dict):
                mismatched.append(str(path))
                continue
            try:
                payload = ctx.store.read_bytes(path)
            except (ConfigurationError, OSError):
                mismatched.append(str(path))
                continue
            actual = {
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            if actual["bytes"] != meta.get("bytes") or actual["sha256"] != meta.get(
                "sha256"
            ):
                mismatched.append(path)
        ctx.check(
            "report source hashes",
            not mismatched,
            ", ".join(mismatched[:5]),
        )
        artifacts = report.get("artifacts") or {}
        html = (
            artifacts.get("html") if isinstance(artifacts, dict) else None
        ) or "analysis/report.html"
        ctx.check(
            "report HTML exists",
            _exists(ctx, html),
            f"{html} missing",
        )
        json_path = artifacts.get("json") if isinstance(artifacts, dict) else None
        ctx.check(
            "report JSON exists",
            _exists(ctx, json_path),
            f"{json_path} missing",
        )
