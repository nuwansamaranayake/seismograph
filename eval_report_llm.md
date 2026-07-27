# Seismograph metamorphic back-check (key-gated)

model: `google/gemini-2.5-flash`   embedder: `openrouter`
acceptance band: 0.6 <= cosine <= 0.995

**Accepted 53/54 variants = 0.98 (95% CI 0.90-1.00)** across 9 statement types.

| statement type | accepted | min score | max score |
|---|---|---|---|
| question | 6/6 | 0.847 | 0.943 |
| numeric | 6/6 | 0.867 | 0.937 |
| negation | 6/6 | 0.853 | 0.947 |
| policy | 6/6 | 0.823 | 0.909 |
| conditional | 6/6 | 0.761 | 0.837 |
| instruction | 6/6 | 0.817 | 0.924 |
| multi_clause | 5/6 | 0.916 | 0.998 |
| terse | 6/6 | 0.837 | 0.856 |
| formal | 6/6 | 0.774 | 0.886 |

## Rejection reasons

- `ok`: 53
- `trivial_copy`: 1

## Negative controls (must all be rejected)

- `off_topic`: rejected (score 0.025, too_dissimilar)
- `contradiction`: rejected (score 0.563, too_dissimilar)
- `number_changed`: rejected (score 0.956, numeric_drift)
