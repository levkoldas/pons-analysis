"""Shared command helpers for cohort files and JSON reads."""

import csv
import json
from pathlib import Path

from pons_analysis.core.errors import ConfigurationError
from pons_analysis.core.evm import addr

from ..runtime import CliSession


def _read_json(case: CliSession, path: Path):
    if path.is_absolute():
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    return case.store.read_json(path)


def _read_csv(case: CliSession, path: Path) -> list[dict[str, str]]:
    if path.is_absolute():
        with path.open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))
    return case.store.read_csv(path)


def _cohort_roots(
    case: CliSession, cohort: list[str], cohort_file: Path | None
) -> list[str]:
    roots = list(cohort)
    if cohort_file:
        exists = (
            cohort_file.exists()
            if cohort_file.is_absolute()
            else case.store.exists(cohort_file)
        )
        if not exists:
            raise ConfigurationError(f"Cohort file not found: {cohort_file}")
        before = len(roots)
        try:
            if cohort_file.suffix == ".json":
                values = _read_json(case, cohort_file)
                if not isinstance(values, list):
                    raise ConfigurationError("Cohort JSON must contain a wallet list")
                roots.extend(values)
            else:
                roots.extend(
                    row["destination_wallet"] for row in _read_csv(case, cohort_file)
                )
        except ConfigurationError:
            raise
        except (OSError, KeyError, TypeError, ValueError, csv.Error) as exc:
            raise ConfigurationError(
                f"Cohort file must contain destination_wallet entries: {cohort_file}"
            ) from exc
        if len(roots) == before:
            raise ConfigurationError(f"Cohort file is empty: {cohort_file}")
    try:
        return [addr(item) for item in roots]
    except ValueError as exc:
        raise ConfigurationError("Invalid cohort wallet address") from exc
