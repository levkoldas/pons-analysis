"""Cross-artifact integrity audit for derived analysis outputs.

This audits derived files only; raw evidence remains owned by the collectors and
the raw `validate` command. It checks window tags, row counts, cross-artifact
wallet coverage, derivation identities, and the standalone report's source
hashes against the current workspace.
"""

from typing import Any

from pons_analysis.storage.store import ArtifactStore
from pons_analysis.validation.derived.checks import CHECK_SEQUENCE
from pons_analysis.validation.derived.context import ValidationContext


def validate_derived(
    store: ArtifactStore,
    minutes: int = 30,
    *,
    decimals: int = 18,
    include_report: bool = True,
) -> dict[str, Any]:
    """Validate derived artifact consistency for a selected window."""
    if minutes < 1:
        raise ValueError("Window duration must be positive")
    ctx = ValidationContext(
        store, minutes, decimals=decimals, include_report=include_report
    )
    ctx.load_summaries()
    for run in CHECK_SEQUENCE:
        run(ctx)
    failures = [entry for entry in ctx.checks if not entry["ok"]]
    result = {
        "minutes": minutes,
        "passed": not failures,
        "checks": len(ctx.checks),
        "failures": failures,
        "results": ctx.checks,
    }
    store.write_json("analysis/derived-validation.json", result)
    return result
