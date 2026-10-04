# Hourly XMR models: price-only and incident-augmented

This folder groups the hourly forecasting work separately from the earlier
incident-only daily model. It is a copied review snapshot of the existing
workspace; retained files, fitted models and historical freezes are preserved
byte for byte. The **588-row incident catalog is included**. Price-series
datasets, price-feature datasets and data-collection material are excluded.
`MANIFEST.json` records every retained copied file's original
location, destination, size and SHA-256.

## Current specification and results

- [NEWMODELS.MD](/Users/c/Documents/Signal/hourly_models/NEWMODELS.MD): the hourly
  specification and catalog-date amendment. Some implementation-status passages
  predate the completed runs; use the result manifests below for actual run status.
- [Price-only training report](/Users/c/Documents/Signal/hourly_models/docs/models/xmr_hourly_price_baseline_v1/TRAINING_REPORT.md).
- [Paired hourly development results](/Users/c/Documents/Signal/hourly_models/docs/models/xmr_hourly_incident_catalog_v2/results/RESULTS.md).
- [Three final models and scalers](/Users/c/Documents/Signal/hourly_models/docs/models/xmr_hourly_incident_catalog_v2/results/FINAL_FROZEN.json):
  price-only, presence-only and full incident models trained on the same population.
- [Reserved-20% OOS results](/Users/c/Documents/Signal/hourly_models/docs/models/xmr_hourly_incident_catalog_v2/oos_v1/results/RESULTS.md).

The common target is gross XMR/USD return strictly above 3% over 120 hours.
The reserve is 2024-10-20 00:00 UTC to 2026-10-03 00:00 UTC, exclusive.
OOS scoring used the frozen final models and training scalers without fitting
or tuning. Retrospective incident timing/loss assumptions, earlier historical
inspection and the amendment's timing remain disclosed in the copied reports.

## Contents

| Location | Contents |
| --- | --- |
| `scripts/` | Two training entry points and the OOS evaluator only |
| `tests/` | Tests for those three model/evaluation entry points |
| `config/models/` | Price-only configuration; incident settings also live in its script and freeze manifests |
| `docs/models/` | Completed hourly reports, folds, regularization selection, coefficients, scalers, scored predictions, paper simulations, plots and OOS results |
| `data/curated/incidents_over_1m.csv` | The unchanged 588-row incident/attack catalog |
| `docs/` | Model/OOS instructions and competition-rule provenance |
| `history/` | Earlier blocked hourly incident-model readiness reports; no fitted model or successful training run |
| `requirements-*.txt` | Existing dependency specifications |

`HOURLY_INCIDENT_MODEL_DESIGN.md` is an early design document. Its proposed
features, target and readiness description are historical; the current
specification and completed freezes supersede them.

## Original workspace and reproduction

Hourly/minute price datasets, coverage files, joined price-feature datasets,
price-review tables, collection/download/build scripts and collection
documentation are excluded. The separate collection/evidence ledger is also
excluded; the retained incident input is the 588-row catalog. Historical blocked
preflights retain their summary reports and manifests, without tabular datasets.
Scored predictions and model-result summaries remain as evaluation artifacts.

Use the price data already maintained in the other repository; this folder does
not duplicate it. The old incident-only model and its runs are excluded.
This is an organizational snapshot, not a standalone reproduction package.
Frozen manifests intentionally
retain original repository paths and checksums, including provenance dependencies
outside this folder. `MANIFEST.json` lists these external dependencies.

Run the original evaluator from the original workspace to verify the completed
OOS outputs without overwriting or retraining:

```sh
cd /Users/c/Documents/Signal
/private/tmp/gqh-model-venv/bin/python -B scripts/evaluate_xmr_hourly_oos.py verify
```

The scripts copied here retain their original path assumptions. Do not run a
copied trainer to create a replacement for an archived run, or rewrite a freeze
to accommodate omitted data or provenance dependencies. The complete original
runs remain in the original workspace. All original files remain in
place. No training, additional OOS scoring, commit, push or deployment was
performed when creating this folder.
