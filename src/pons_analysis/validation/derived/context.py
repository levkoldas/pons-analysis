"""Shared, memoized access to derived artifacts during validation."""

from __future__ import annotations

from typing import Any

from pons_analysis.core.errors import ConfigurationError
from pons_analysis.storage.store import ArtifactStore

WINDOWED_ARTIFACTS = (
    "positions",
    "trajectory",
    "candles",
    "holders",
    "flow",
    "lifecycle",
    "execution",
    "fees",
    "entry-cohorts",
    "retention",
    "cluster-quality",
    "route-performance",
    "cohort",
    "provenance",
    "wallets",
)


def wallet_set(rows: list[dict[str, str]]) -> set[str]:
    return {row["wallet"].lower() for row in rows if row.get("wallet")}


def require_summary(
    ctx: ValidationContext,
    summary: dict[str, Any] | None,
    rows: list[Any],
    label: str,
) -> None:
    if rows and summary is None:
        ctx.check(
            f"{label} summary present", False, f"{label} rows exist without summary"
        )


class ValidationContext:
    """Lazy artifact reader and check accumulator for one window."""

    def __init__(
        self,
        store: ArtifactStore,
        minutes: int,
        *,
        decimals: int = 18,
        include_report: bool = True,
    ) -> None:
        self.store = store
        self.minutes = minutes
        self.decimals = decimals
        self.include_report = include_report
        self.summaries: dict[str, dict[str, Any]] = {}
        self.checks: list[dict[str, Any]] = []
        self._rows: dict[str, list[dict[str, str]]] = {}
        self._json: dict[str, dict[str, Any] | None] = {}
        self._json_errors: set[str] = set()

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(
            {"name": name, "ok": bool(ok), "detail": "" if ok else detail}
        )

    def rows(self, relative: str) -> list[dict[str, str]]:
        if relative not in self._rows:
            self._rows[relative] = (
                self.store.read_csv(relative) if self.store.exists(relative) else []
            )
        return self._rows[relative]

    def json(self, relative: str) -> dict[str, Any] | None:
        if relative not in self._json:
            try:
                payload = self.store.read_json(relative)
            except ConfigurationError:
                payload = None
                if self.store.exists(relative):
                    self._json_errors.add(relative)
                    self.check(f"{relative} JSON", False, relative)
            else:
                if not isinstance(payload, dict) and self.store.exists(relative):
                    self._json_errors.add(relative)
                    self.check(f"{relative} JSON", False, relative)
            self._json[relative] = payload if isinstance(payload, dict) else None
        return self._json[relative]

    def window(self, group: str, leaf: str) -> str:
        return f"analysis/{group}-{self.minutes}/{leaf}"

    def summary(self, name: str) -> dict[str, Any]:
        return self.summaries.get(name, {})

    def load_summaries(self) -> None:
        for name in WINDOWED_ARTIFACTS:
            relative = self.window(name, "summary.json")
            if not self.store.exists(relative):
                continue
            payload = self.json(relative)
            if payload is None:
                if relative not in self._json_errors:
                    self.check(f"{name} summary JSON", False, relative)
                continue
            self.summaries[name] = payload
            self.check(
                f"{name} window",
                payload.get("minutes") == self.minutes,
                f"{payload.get('minutes')} != {self.minutes}",
            )

    def subset(self, name: str, rows: list[dict[str, str]]) -> set[str]:
        selected = wallet_set(rows)
        self.check(
            f"{name} wallets subset",
            selected <= self.wallets,
            f"{len(selected - self.wallets)} unknown wallets",
        )
        return selected

    @property
    def positions(self) -> list[dict[str, str]]:
        return self.rows(self.window("positions", "positions.csv"))

    @property
    def transactions(self) -> list[dict[str, str]]:
        return self.rows(self.window("positions", "transactions.csv"))

    @property
    def lots(self) -> list[dict[str, str]]:
        return self.rows(self.window("positions", "lots.csv"))

    @property
    def trade_legs(self) -> list[dict[str, str]]:
        return self.rows(self.window("positions", "trade_legs.csv"))

    @property
    def wallets(self) -> set[str]:
        return wallet_set(self.positions)

    @property
    def position_totals(self) -> dict[str, Any]:
        return self.summary("positions").get("totals") or {}

    @property
    def fee_wallets(self) -> list[dict[str, str]]:
        return self.rows(self.window("fees", "wallets.csv"))

    @property
    def fee_groups(self) -> list[dict[str, str]]:
        return self.rows(self.window("fees", "groups.csv"))

    @property
    def execution(self) -> list[dict[str, str]]:
        return self.rows(self.window("execution", "wallets.csv"))

    @property
    def lifecycle(self) -> list[dict[str, str]]:
        return self.rows(self.window("lifecycle", "wallets.csv"))

    @property
    def lifecycle_gas(self) -> dict[str, int]:
        return {
            row["wallet"].lower(): int(row.get("gas_quote_raw") or 0)
            for row in self.lifecycle
        }

    @property
    def trajectory(self) -> list[dict[str, str]]:
        return self.rows(self.window("trajectory", "trajectory.csv"))

    @property
    def candles(self) -> list[dict[str, str]]:
        return self.rows(self.window("candles", "candles.csv"))

    @property
    def holders(self) -> list[dict[str, str]]:
        return self.rows(self.window("holders", "timeline.csv"))

    @property
    def flow(self) -> list[dict[str, str]]:
        return self.rows(self.window("flow", "buckets.csv"))

    @property
    def flow_wallets(self) -> list[dict[str, str]]:
        return self.rows(self.window("flow", "wallets.csv"))

    @property
    def entry_cohorts(self) -> list[dict[str, str]]:
        return self.rows(self.window("entry-cohorts", "cohorts.csv"))

    @property
    def entry_wallets(self) -> list[dict[str, str]]:
        return self.rows(self.window("entry-cohorts", "wallets.csv"))

    @property
    def retention_cohorts(self) -> list[dict[str, str]]:
        return self.rows(self.window("retention", "cohorts.csv"))

    @property
    def retention_wallets(self) -> list[dict[str, str]]:
        return self.rows(self.window("retention", "wallets.csv"))

    @property
    def retention_timeline(self) -> list[dict[str, str]]:
        return self.rows(self.window("retention", "timeline.csv"))

    @property
    def provenance(self) -> list[dict[str, str]]:
        return self.rows(self.window("provenance", "wallets.csv"))

    @property
    def scorecard(self) -> list[dict[str, str]]:
        return self.rows(self.window("wallets", "wallets.csv"))

    @property
    def route_rows(self) -> list[dict[str, str]]:
        return self.rows(self.window("route-performance", "routes.csv"))

    @property
    def route_wallets(self) -> list[dict[str, str]]:
        return self.rows(self.window("route-performance", "wallets.csv"))

    @property
    def cluster_quality(self) -> list[dict[str, str]]:
        return self.rows(self.window("cluster-quality", "clusters.csv"))

    @property
    def clusters(self) -> list[dict[str, str]]:
        return self.rows("analysis/clusters/clusters.csv")

    @property
    def cluster_membership(self) -> list[dict[str, str]]:
        return self.rows("analysis/clusters/wallets.csv")

    @property
    def cohort_generations(self) -> list[dict[str, str]]:
        return self.rows(self.window("cohort", "generations.csv"))

    @property
    def rotations(self) -> list[dict[str, str]]:
        return self.rows(self.window("window", "rotations.csv"))

    @property
    def window_summary(self) -> dict[str, Any]:
        return self.json(self.window("window", "summary.json")) or {}

    @property
    def funding_edges(self) -> list[dict[str, str]]:
        return self.rows("analysis/funding/edges.csv")

    @property
    def funding_wallets(self) -> list[dict[str, str]]:
        return self.rows("analysis/funding/wallets.csv")

    @property
    def funding_summary(self) -> dict[str, Any] | None:
        return self.json("analysis/funding/summary.json")

    @property
    def launch_routes(self) -> list[dict[str, str]]:
        return self.rows("analysis/launch/routes.csv")

    @property
    def launch_trades(self) -> list[dict[str, str]]:
        return self.rows("analysis/launch/trades.csv")

    @property
    def launch_holders(self) -> list[dict[str, str]]:
        return self.rows("analysis/launch/holders.csv")

    @property
    def launch_summary(self) -> dict[str, Any] | None:
        return self.json("analysis/launch/summary.json")

    @property
    def report(self) -> dict[str, Any] | None:
        if not self.include_report:
            return None
        roots = []
        own = self.store.path("analysis")
        if own.is_dir():
            roots.append(own)
        if getattr(self.store, "fallback_analysis", False):
            base = getattr(self.store, "base", None)
            if base is not None and base.path("analysis").is_dir():
                roots.append(base.path("analysis"))
        candidates: list[tuple[str, dict[str, Any]]] = []
        for root in roots:
            for path in sorted(root.rglob("*.json")):
                relative = f"analysis/{path.relative_to(root)}"
                payload = self.json(relative)
                if (
                    isinstance(payload, dict)
                    and "schema_version" in payload
                    and isinstance(payload.get("sources"), dict)
                    and isinstance(payload.get("artifacts"), dict)
                    and isinstance(payload["artifacts"].get("html"), (str, type(None)))
                ):
                    candidates.append((relative, payload))
        if not candidates:
            return None
        default = [item for item in candidates if item[0] == "analysis/report.json"]
        return (default or candidates)[0][1]
