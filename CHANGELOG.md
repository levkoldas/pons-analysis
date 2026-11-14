# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Distribution is GitHub-only: install from the repository or a tagged release
  wheel. PyPI publication is not enabled.
- Tag pushes now build and attach sdist and wheel assets to a GitHub Release.

## [0.1.0] - 2026-11-13

First public release.

### Added

- Typed `LaunchRun` session for collection, analysis, validation, and optional
  persistence.
- `Pons` facade with explicit launch construction and on-chain discovery.
- Deterministic accounting engines for positions, fees, flow, holders, cohorts,
  retention, routes, clusters, funding, provenance, wallets, and market
  trajectory.
- Raw and derived validation passes with workspace manifests.
- Immutable `Table` results with optional Polars, Arrow, pandas, NumPy, DuckDB,
  Parquet, and NetworkX adapters.
- Optional Typer/Rich CLI and deterministic HTML/JSON report renderer.
- File-based evidence and SHA-256-addressed provider caches; offline mode.

### Notes

- Python 3.12 or newer is required.
- Core, dataframe, SQL, graph, and CLI dependencies are split into extras.
- Analyses are read-only with respect to raw evidence.
