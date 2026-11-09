"""The front door in both forms: the built dashboard when present, the single-file page
when not. Either way a browser gets a page and the API keeps answering."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main
from app.main import mount_front_door


def _app_with_health() -> FastAPI:
    application = FastAPI()

    @application.get("/health")
    def health():
        return {"status": "ok"}

    return application


def test_without_a_build_the_single_file_page_serves(tmp_path):
    application = _app_with_health()
    assert mount_front_door(application, tmp_path) == "fallback"
    r = TestClient(application).get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "Seismograph" in r.text


def test_the_suite_itself_runs_on_the_fallback():
    """WEB_DIR is not set under test, so the app under test has no dashboard mounted:
    every other test asserts against the page this process really serves."""
    assert main.FRONT_DOOR == "fallback"


def test_with_a_build_the_export_is_the_front_door_and_api_routes_still_win(tmp_path):
    (tmp_path / "index.html").write_text("<html><body>dashboard home</body></html>", encoding="utf-8")
    (tmp_path / "guide").mkdir()
    (tmp_path / "guide" / "index.html").write_text("<html><body>the guide</body></html>", encoding="utf-8")
    (tmp_path / "404.html").write_text("<html><body>no such page</body></html>", encoding="utf-8")
    (tmp_path / "llms.txt").write_text("# Seismograph\n", encoding="utf-8")

    application = _app_with_health()
    assert mount_front_door(application, tmp_path) == "dashboard"
    client = TestClient(application)

    assert "dashboard home" in client.get("/").text
    assert "the guide" in client.get("/guide/").text
    assert client.get("/llms.txt").text.startswith("# Seismograph")
    assert client.get("/health").json() == {"status": "ok"}, "API routes are matched before the mount"
    missing = client.get("/no/such/page")
    assert missing.status_code == 404 and "no such page" in missing.text
