"""Dependency-ordered full refresh for a :class:`LaunchRun`."""

from collections.abc import Iterable

from pons_analysis.results import RefreshResult
from pons_analysis.run import LaunchRun


def refresh(
    run: LaunchRun,
    minutes: int,
    *,
    cohort: Iterable[str] = (),
    persist: bool | None = None,
) -> RefreshResult:
    """Run every available analysis and both validation passes."""

    return run.refresh(minutes, cohort=cohort, persist=persist)
