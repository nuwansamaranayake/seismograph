"""Serve the API and the built dashboard locally, for development and the guide.

    python scripts/dev_serve.py            # http://127.0.0.1:8765
    python scripts/dev_serve.py --database-url postgresql+psycopg://user:pw@host:5432/db

Development only. It sets APP_ENV=development and leaves the bearer token empty, which
app.main refuses to do anywhere else. The database is whatever DATABASE_URL names; it
must already be migrated (`alembic upgrade head`). Nothing here is a fallback: if the
database is down the API says so.

The dashboard is served from web/out when that build exists (`cd web && npm run build`).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def main() -> None:
    if "--database-url" in sys.argv:
        os.environ["DATABASE_URL"] = sys.argv[sys.argv.index("--database-url") + 1]
    os.environ["APP_ENV"] = "development"
    os.environ["SMOKE_TEST_TOKEN"] = ""
    os.environ.setdefault(
        "DATABASE_URL", "postgresql+psycopg://aignite:aignite@127.0.0.1:55440/seismograph")
    os.environ.setdefault("WEB_DIR", str(REPO / "web" / "out"))
    os.chdir(REPO)
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.getenv("DEV_PORT", "8765")))


if __name__ == "__main__":
    main()
