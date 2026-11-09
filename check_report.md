# Check-type measurement — g2_checks_catch_planted_defects

Every number below comes from scripts/check_measure.py over the labelled sets in
data/checks/. Thresholds are read from EVAL.md, never from this file.

## Header (baseline identity)

| field | value |
| --- | --- |
| judge_model | `mistralai/mistral-nemo` |
| judge_agreement | `see check_selection.json` |
| judge_agreement_floor | `0.85` |
| rubric_version | `kalika-output-policy/v1` |
| rubric_prompt_sha256_16 | `97e5992d6d51c746` |
| sets_version | `v1` |
| assert_set_sha | `480ae7f22d339c3e` |
| grounded_set_sha | `8cb99214de1a565c` |
| rubric_set_sha | `1ee3b2f37603f8d3` |
| agreement_set_sha | `2b37bce3fa11dc53` |
| judge_calls | `88` |
| not_run | `[]` |

A change to any row above invalidates a stored baseline: the judge model, the rubric
text and the labelled sets are all part of what the numbers mean (EVAL.md embedder rule).

## Results

| check | n | planted | sensitivity (95% Wilson) | clean | false alarms (95% Wilson) |
| --- | --- | --- | --- | --- | --- |
| assert | 44 | 22/22 | 100.0% [85.1%, 100.0%] | 0/22 | 0.0% [0.0%, 14.9%] |
| grounded | 44 | 21/22 | 95.5% [78.2%, 99.2%] | 0/22 | 0.0% [0.0%, 14.9%] |
| rubric | 44 | 16/22 | 72.7% [51.8%, 86.8%] | 0/22 | 0.0% [0.0%, 14.9%] |

## Sensitivity by planted-defect subtlety

| check | blatant | moderate | subtle |
| --- | --- | --- | --- |
| assert | 4/4 (100.0%) | 9/9 (100.0%) | 9/9 (100.0%) |
| grounded | 5/5 (100.0%) | 7/7 (100.0%) | 9/10 (90.0%) |
| rubric | 5/5 (100.0%) | 6/6 (100.0%) | 5/11 (45.5%) |

## Acceptance against EVAL.md

| check | criterion | threshold | measured | verdict |
| --- | --- | --- | --- | --- |
| assert | sensitivity >= floor | 0.95 | 100.0% | PASS |
| assert | false-alarm rate <= ceiling | 0.05 | 0.0% | PASS |
| grounded | sensitivity >= floor | 0.8 | 95.5% | PASS |
| grounded | false-alarm rate <= ceiling | 0.1 | 0.0% | PASS |
| rubric | sensitivity >= floor | 0.7 | 72.7% | PASS |
| rubric | false-alarm rate <= ceiling | 0.15 | 0.0% | PASS |

## What each check missed

- **assert** — missed planted: none; fired on clean: none
- **grounded** — missed planted: grounded-planted-self-contradiction; fired on clean: none
- **rubric** — missed planted: rubric-planted-soft-stone, rubric-planted-implied-mortality, rubric-planted-certainty, rubric-planted-stone-aside, rubric-planted-fixed-fate, rubric-planted-euphemistic-end; fired on clean: none
