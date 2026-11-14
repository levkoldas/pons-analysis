import importlib.metadata
import subprocess
import sys

import pons_analysis
from pons_analysis import RunConfig


def test_version_matches_installed_metadata() -> None:
    assert pons_analysis.__version__ == importlib.metadata.version("pons-analysis")


def test_every_public_name_is_importable() -> None:
    missing = [
        name for name in pons_analysis.__all__ if not hasattr(pons_analysis, name)
    ]
    assert missing == []


def test_user_agent_matches_version() -> None:
    assert RunConfig().user_agent == f"pons-analysis/{pons_analysis.__version__}"


def test_import_does_not_load_optional_dependencies() -> None:
    script = """
import sys
import pons_analysis

optional = {"httpx", "pydantic", "polars", "pandas", "numpy", "duckdb", "networkx"}
loaded = sorted(optional & set(sys.modules))
if loaded:
    raise SystemExit(f"eagerly imported: {loaded}")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
