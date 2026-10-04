# Frozen hourly XMR OOS evaluator

`scripts/evaluate_xmr_hourly_oos.py` evaluates the three final models embedded
in `docs/models/xmr_hourly_incident_catalog_v2/results/FINAL_FROZEN.json`.
It does not train, estimate scalers, select parameters, or alter training files.

The calendar reserve is **2024-10-20 00:00 UTC through 2026-10-03 00:00 UTC,
exclusive**. Only classification decisions whose complete 120-hour target
ends at or before the reserve's ending boundary are scored. A boundary close
comes from the completed previous hour. Earlier prices provide backward
lookbacks; they are never additional evaluation decisions. The target is
gross XMR/USD return strictly greater than **3%**. All models share one cohort.

The frozen combined XMR `close_usd` and BTC `close_usd` columns, 300-second
freshness limit, positive finite prices, 25 valid consecutive volatility
closes and unchanged catalog-date incident mapping are used. Existing review
dispositions are preserved; any newly encountered flagged close remains
unresolved and excluded from every required feature, target, fill, exit and
mark. No return-based review or relaxed filtering is performed.

Run with Python 3.12 and NumPy (the local model virtual environment is
`/private/tmp/gqh-model-venv/bin/python`):

```sh
python -B scripts/evaluate_xmr_hourly_oos.py prepare
python -B scripts/evaluate_xmr_hourly_oos.py run
python -B scripts/evaluate_xmr_hourly_oos.py verify
```

`prepare` verifies archived model/source hashes and saves an evaluation freeze,
price dispositions, outcome-free features and eligibility/exclusion ledgers.
`run` requires this freeze and scores once. `verify` reproduces the complete
outputs without writing or fitting. Existing preparation/results cannot be
overwritten by another `prepare`/`run`.

Outputs live separately in `docs/models/xmr_hourly_incident_catalog_v2/oos_v1`.
`results/RESULTS.md` and `summary.json` report overall, incident-active and
ordinary log loss, Brier score, AUC and accuracy, with frozen training-prevalence
benchmarks. Calibration, probability distributions and paired 168-hour block
uncertainty are included. An empty or one-class subset has unavailable AUC.

The frozen paper simulation uses p >= 0.60, 10% equity, one outright long
position, next-hour fills and a 120-hour hold from the fill. It reports 2% costs,
4% cost stress, buy-and-hold with 100% initial exposure, and cash. Its signals use
feature-eligible hours without filtering on future target/exit validity.
Missing fills are unfilled orders, missing scheduled exits are unresolved,
and missing position marks prevent a complete drawdown estimate.

Historical outcomes from this reserve were examined in earlier association
analyses, although neither the original logistic training nor these three
current model fits used the reserved interval. The price-only outer development
scores were also inspected before the catalog-date amendment. Retrospective
dates and eventual losses can contain unavailable-at-the-time information.
Retain these disclosures: these are frozen-model reserved-period evaluations,
not an untouched project-wide holdout or a verified live incident trading edge.
Do not iterate settings on the resulting OOS scores. No commit or push is made.
