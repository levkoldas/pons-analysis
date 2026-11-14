"""CLI assembly: importing command modules registers them on the Typer apps."""

from .commands import admin, analyze, collect  # noqa: F401
from .runtime import app, run

__all__ = ["app", "run"]
