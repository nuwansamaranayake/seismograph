"""The front door: one self-contained HTML file, no framework, no build step.

Version, commit and build time are injected from environment variables that the Dockerfile
bakes from build arguments. When a value is absent it renders as "unknown" rather than a
plausible-looking placeholder: an unverified number on a public page is a fabricated number.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from .config import settings

_PAGE = Path(__file__).resolve().parent / "static" / "index.html"


@lru_cache(maxsize=1)
def _template() -> str:
    return _PAGE.read_text(encoding="utf-8")


def render() -> str:
    """Substitute the build-time facts into the static page."""
    return (_template()
            .replace("__VERSION__", os.getenv("APP_VERSION", "unreleased"))
            .replace("__SHA__", os.getenv("GIT_SHA", "unknown"))
            .replace("__BUILT__", os.getenv("BUILD_TIME", "unknown"))
            .replace("__ENV__", settings.app_env.value))
