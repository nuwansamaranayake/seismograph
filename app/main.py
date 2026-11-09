import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from groundwork import Env, build_version

from .config import settings
from .fixtures import load_synthetic_fixture
from .frontpage import render as render_front_page
from .read_api import router as read_router
from .routes import router


def require_production_auth(cfg=settings) -> None:
    """Empty SMOKE_TEST_TOKEN means bearer auth is OFF (routes._auth). That is a documented
    development convenience only. Outside development it would run the mutating endpoints
    unauthenticated, so refuse to start (Standards 2/3: real token, fail loud) — the same
    guard shape as the demo-fixture 503 below."""
    if cfg.app_env is not Env.development and not cfg.smoke_test_token:
        raise RuntimeError(
            f"SMOKE_TEST_TOKEN is empty with APP_ENV={cfg.app_env.value}: mutating "
            "endpoints would serve unauthenticated. Set SMOKE_TEST_TOKEN; auth-off is "
            "allowed only in development."
        )


require_production_auth()

app = FastAPI(title="Seismograph", version=build_version())
app.include_router(router)
app.include_router(read_router)


@app.get("/health")
def health():
    return {"status": "ok", "env": settings.app_env.value}


@app.get("/api/v1/demo")
def demo():
    # Fixture data is allowed only in development. Standard 3: fail loud elsewhere.
    if settings.app_env is not Env.development:
        raise HTTPException(status_code=503, detail="demo fixture disabled outside development")
    items = load_synthetic_fixture()
    if not items:
        raise HTTPException(status_code=500, detail="synthetic fixture is empty")
    return {"items": items}



def mount_front_door(application: FastAPI, web_dir: Path) -> str:
    """The front door. Public by design: a browser must get a page, not a 404.

    When the built dashboard is present (the image bakes the Next.js static export at
    /srv/web) it IS the front door: the whole export is mounted last, so every API route
    above still wins and an unknown path gets the export's own 404 page. Without a build
    (a source checkout, the test suite) the single-file page serves. Both carry the
    EVAL.md limits sentence verbatim, and the gate asserts that against whichever is live.
    """
    if (web_dir / "index.html").is_file():
        application.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
        return "dashboard"

    @application.get("/", response_class=HTMLResponse, include_in_schema=False)
    def root() -> HTMLResponse:
        return HTMLResponse(content=render_front_page(),
                            media_type="text/html; charset=utf-8")

    return "fallback"


FRONT_DOOR = mount_front_door(app, Path(os.getenv("WEB_DIR", "/srv/web")))
