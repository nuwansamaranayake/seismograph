# Seismograph golden-defect eval report

scenarios per kind: 20  (baseline 30, monitored 60, n 20, onset K=15)

| metric | value | bound | pass |
|---|---|---|---|
| jump latency median | 0.0 | <= 3 | PASS |
| drift latency median | 1.0 | <= 10 | PASS |
| sensitivity | 1.0 | >= 0.90 | PASS |
| false alarm rate | 0.0 | <= 0.01 | PASS |
| flake detection | 1.0 | >= 0.90 | PASS |
