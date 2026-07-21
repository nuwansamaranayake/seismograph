# Contributing to Seismograph

Part of the AiGNITE portfolio. Read `DOCTRINE.md` before your first change.

## Setup

1. Create a virtual environment (Python 3.12+):

   ```
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   source .venv/bin/activate   # macOS / Linux
   ```

2. Install (editable) with dev tooling:

   ```
   pip install -e ../groundwork
   pip install -e .[dev]
   ```

   > `uv` is the preferred tool once available (`uv sync`); until then use `pip`.

3. Copy `.env.example` to `.env` and populate the required keys.

## Definition of done

- `make lint` (ruff) passes.
- `make test` (pytest) passes.
- `make smoke` passes against a running instance (apps only).
- `contracts.md` and `CHANGELOG.md` updated.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`,
`chore:`, `docs:`, `test:`, `refactor:`. One logical change per commit.

## Good first issue

Look for issues labeled `good first issue`. Extending the synthetic dataset in
`data/synthetic/` or tightening a verification gate is a friendly place to start.
