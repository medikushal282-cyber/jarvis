# JARVIS Agent Brain

## Memory Learning Benchmark

To run the learning benchmark:
```bash
python -m brain.cli benchmark --learning --runs 10
```

### Results (Fake LLM)

```
objective: checkout-api is returning 5xx errors since this morning. Find out why and fix it if you can.
profile:   devops    runs per arm: 10

metric                           memory OFF                 memory ON
---------------------------------------------------------------------
runs                                     10                        10
steps to completion (mean)        2.00 (±0.00)        3.8 (+90.0% worse)
tool errors (mean)                0.00 (±0.00)           0 (no baseline)
corrections needed (mean)         1.00 (±0.00)     0.1 (-90.0% improved)
success rate                           0.0%                     90.0%
```

**Note**: The steps to completion is higher for memory ON because the successful (informed) path legitimately takes more steps than the naive failing path.
