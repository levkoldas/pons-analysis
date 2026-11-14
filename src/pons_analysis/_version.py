"""Single source of truth for the distribution version.

``pyproject.toml`` reads this module when building, so the installed metadata and
:data:`pons_analysis.__version__` cannot drift apart.
"""

__version__ = "0.1.0"
