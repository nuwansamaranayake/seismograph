# Quality report

Generated 2026-11-09T17:26:45Z by `python scripts/quality.py` at commit `49a02d9`.

**Gate: PASS.** The lowest component is 98.00 against a floor of 96. Mean of the components: 99.74.

| Component | Score | Floor met | Measured |
|---|---|---|---|
| backend tests | 100.00 | yes | 600 of 600 passed, 0 skipped |
| backend coverage | 99.87 | yes | 2958 of 2959 statements, 798 of 802 branches |
| backend lint | 100.00 | yes | 0 ruff findings, rules F,E4,E7,E9,B,I,UP,SIM |
| backend types | 100.00 | yes | 0 mypy errors on app/ |
| complexity | 98.00 | yes | 245 of 250 functions at complexity <= 10. Over: map_answers, run_assert_check, run_suite, run_suite_cli, validate_against_schema |
| frontend tests | 100.00 | yes | 207 of 207 passed |
| frontend coverage | 99.75 | yes | statements 100%, branches 99.75%, functions 100%, lines 100% |
| frontend lint | 100.00 | yes | 0 eslint findings |
| frontend types | 100.00 | yes | 0 tsc errors |

The gate is the minimum, not the mean. A component that could not be measured scores 0.
