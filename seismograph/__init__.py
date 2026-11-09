"""`python -m seismograph` entry point.

The implementation package is `app` (historical; see pyproject). This shim
exists so the project name on the command line matches the project name in
pyproject.toml. It adds nothing and forks nothing.
"""
from app.cli import main

__all__ = ["main"]
