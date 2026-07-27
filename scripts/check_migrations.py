import os
import sys
from sqlalchemy import create_engine, text


def main():
    expected_raw = os.getenv("EXPECTED_TABLE_COUNT")
    if not expected_raw:
        # Standard 4: the table-count assertion must never be skippable by a missing env
        # var. An unset expectation is a configuration failure, not a pass.
        print("MIGRATION CHECK FAILED: EXPECTED_TABLE_COUNT is not set", file=sys.stderr)
        sys.exit(1)
    expected = int(expected_raw)
    url = os.environ["DATABASE_URL"]
    with create_engine(url).connect() as c:
        n = c.execute(
            text("select count(*) from information_schema.tables where table_schema='public'")
        ).scalar_one()
    if n != expected:
        print(f"MIGRATION CHECK FAILED: expected {expected} tables, found {n}", file=sys.stderr)
        sys.exit(1)
    print(f"MIGRATION OK: {n} tables")


if __name__ == "__main__":
    main()
