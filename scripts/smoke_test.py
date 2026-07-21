import os
import sys
import httpx

BASE = f"http://{os.getenv('API_HOST', '127.0.0.1')}:{os.getenv('API_PORT', '8000')}"
TOKEN = os.getenv("SMOKE_TEST_TOKEN", "")


def check(path: str):
    r = httpx.get(BASE + path, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=10)
    r.raise_for_status()
    body = r.json()
    assert body, f"{path} returned an empty body"
    return body


def main():
    check("/health")
    data = check("/api/v1/demo")            # a real business endpoint, not just health
    assert data.get("items"), "demo endpoint returned no items"
    print("SMOKE OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"SMOKE FAILED: {e}", file=sys.stderr)
        sys.exit(1)
