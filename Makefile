PYTHON ?= python3
LINT_IMPORTS ?= $(shell command -v lint-imports 2>/dev/null || echo '$(dir $(PYTHON))lint-imports')

.PHONY: check format test build clean

check:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m mypy
	$(PYTHON) -m pytest -q
	$(LINT_IMPORTS)
	$(PYTHON) -c "import pons_analysis"

format:
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .

test:
	$(PYTHON) -m pytest -q

build:
	$(PYTHON) -m build

clean:
	rm -rf build dist .pytest_cache .mypy_cache .ruff_cache .hypothesis .import_linter_cache
