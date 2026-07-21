import os
import sys
from sqlalchemy import create_engine, text

EXPECTED = int(os.getenv("EXPECTED_TABLE_COUNT", "0"))


def main():
    url = os.environ["DATABASE_URL"].replace("+psycopg", "")
    with create_engine(url).connect() as c:
        n = c.execute(
            text("select count(*) from information_schema.tables where table_schema='public'")
        ).scalar_one()
    if EXPECTED and n != EXPECTED:
        print(f"MIGRATION CHECK FAILED: expected {EXPECTED} tables, found {n}", file=sys.stderr)
        sys.exit(1)
    print(f"MIGRATION OK: {n} tables")


if __name__ == "__main__":
    main()
