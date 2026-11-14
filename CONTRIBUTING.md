# Contributing

Thanks for improving `pons-analysis`.

## Setup

Python 3.12 or newer is required.

```bash
git clone https://github.com/levkoldas/pons-analysis.git
cd pons-analysis
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

With [uv](https://docs.astral.sh/uv/):

```bash
uv venv
uv pip install -e '.[dev]'
```

## Quality gate

Run the full check before opening a pull request:

```bash
make check
```

This runs Ruff linting and formatting, mypy on the typed public API, the pytest
suite, the import-linter architecture contract, and an import smoke test. The CI
workflow runs the same gate on Python 3.12, 3.13, and 3.14.

If you do not have the dev extra activated, point the Makefile at your
interpreter:

```bash
make check PYTHON=.venv/bin/python
```

## Guidelines

- Keep the layered architecture intact. `analytics` must not import
  `presentation`; provider and store protocols belong in `ports.py`.
- Public behaviour changes need tests and a `CHANGELOG.md` entry.
- Never commit API keys, credential files, workspaces, caches, or raw evidence.
  `Credentials` objects redact keys in `repr`; keep it that way.
- Prefer typed results and `Table` over ad-hoc dictionaries at the public
  boundary.
- Match the existing style: explicit dataclasses, typed modules, and no
  environment or working-directory reads on import.

## Reporting bugs

Open an issue with the command or Python snippet that reproduces the problem,
the expected and actual results, the Python version, and the PONS token address
(or a sanitized description). Do not include API keys or private wallet data.

Security issues: see [SECURITY.md](SECURITY.md).
