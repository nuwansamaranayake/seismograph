from fastapi import FastAPI, HTTPException
from groundwork import Env
from .config import settings
from .fixtures import load_synthetic_fixture
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

app = FastAPI(title="Seismograph")
app.include_router(router)


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
