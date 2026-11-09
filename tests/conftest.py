"""Hermetic test environment.

app.config builds its settings at import time from .env, so before this file
existed the suite's result depended on whatever the operator happened to have in
their local .env. Populating SMOKE_TEST_TOKEN there for the g0 c2 production
check silently turned bearer auth ON for the tests and 8 of them started
returning 401 — a red suite caused by a file no test ever mentions.

Tests declare the environment they need. The auth-on path is still covered:
test_business_reads_require_bearer_when_token_set sets the token explicitly, and
test_production_with_empty_token_refuses_startup monkeypatches app_env.

This must run before app.config is imported, which pytest guarantees: conftest
is loaded ahead of the test modules that import the app.
"""
import os

# Env vars take precedence over .env in pydantic-settings, so these win.
os.environ["SMOKE_TEST_TOKEN"] = ""      # empty => bearer auth off (app.routes._auth)
os.environ["APP_ENV"] = "development"    # required for auth-off; see require_production_auth
