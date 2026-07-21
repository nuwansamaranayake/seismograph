from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class DemoResponse(BaseModel):
    """Response model for GET /api/v1/demo.

    Item shape is intentionally permissive: each app's synthetic domain differs. The
    contract that matters here is `items` is a non-empty list (asserted by the smoke test).
    """

    items: list[dict[str, Any]]
