# Hourly price-only logistic baseline

This implements the market baseline (features 1–5) in `NEWMODELS.MD`.
The XMR input is `data/analysis/xmr_usd_btc_combined_1h.csv` (`close_usd`),
and the BTC input is `data/analysis/btc_usd_1h.csv`. The combined series contains
source-labelled Kraken USD observations and same-minute Binance XMR/BTC ×
Kraken BTC/USD conversion proxies. Its raw XMR/BTC column is not the target.
It uses every eligible hourly decision, with no incident inputs, incident
filtering, or historical incident-coverage gate. It tests forecasts of a gross
XMR/USD 120-hour return exceeding the selected 3%, 4% or 5% hurdle. BTC is a
lagged predictor, without a hedge or future BTC target.

The existing protocol's calendar boundaries, 300-second price freshness,
25 valid consecutive XMR boundary prices for volatility, training-only
scalers, chronological nested L2 selection, strict target comparison, and
120-hour target-end purges are retained. Missing prices are never filled.
The 20% reservation starts October 20, 2024; numeric source values at or
after that bar-start cutoff are not parsed. The final prior bar's close,
ending exactly at the cutoff, can close a development label. Full source
hashes are retained for provenance without analyzing reserved values.

Initial A selects the hurdle using the documented fixed paper policy and
constraints. A fallback 3% target is descriptive if none qualify. The chosen
hurdle and policy are written to `SELECTED.json` before outer scores.
L2 is reselected only inside each expanding training period. Optimizer
convergence is checked using float64 Newton steps on mean binary cross
entropy plus `lambda/2 * sum(beta**2)`, with an unpenalized intercept.

One execution correction is explicit: paper fills occur at the next completed
hour's close, rather than the close used by the signal, and positions last
120 hours from that fill. The classification target keeps NEWMODELS.MD's
original completed-close clock, so paper returns and label returns can differ.
Future target availability never gates a simulated entry. Missing scheduled
exits remain unresolved; missing intermediate marks remain unknown and make
the economic hurdle candidate ineligible because complete drawdown is unknown.
This correction matches the addition to NEWMODELS.MD and is recorded in the
pre-run manifest; the source design document is preserved.

Outputs include log loss, Brier, AUC, accuracy, calibration bins/probability
quantiles, training-prevalence comparisons, and paired 168-hour calendar-block
bootstrap intervals for loss differences. Hourly overlapping labels are not
independent trials. `calibration_curve.csv` provides the reliability-curve
coordinates per outer fold and pooled; `probability_distribution.csv` provides
the pooled histogram. `cohort.csv` retains every development input/target and
selected-close audit field. `FINAL_FROZEN.json` pins the final model/scaler and
policy before any separate reserved evaluation. Portfolio outputs include return, daily volatility/Sharpe,
observed drawdown, turnover, investment time, trades and daily equity curves,
double-cost stress, XMR buy-and-hold and cash. Crypto annualization uses 365
days. Calendar blocks beginning at fractional days sample every 24 hours from
the block start, with a final partial interval disclosed.

The buy-and-hold benchmark invests available cash after its entry cost; the
model policy invests 10% of equity. This exposure difference is intentional
and must accompany comparisons. Missing prices can leave either policy
incomplete; an observed drawdown with missing marks is not a complete risk
estimate. These results alone do not establish capacity or executable fills.

Use Python 3.10+ and NumPy from `requirements-analysis.txt`. An existing local
runtime is `/private/tmp/gqh-model-venv/bin/python`:

```sh
python scripts/train_xmr_hourly_baseline.py prepare
python scripts/train_xmr_hourly_baseline.py check
python -m unittest discover -s tests -p 'test_xmr_hourly_baseline.py'
python scripts/train_xmr_hourly_baseline.py freeze
python scripts/train_xmr_hourly_baseline.py run
python scripts/train_xmr_hourly_baseline.py run --verify
```

`prepare` verifies source checksums against the existing independent-validation
and coverage manifests, and writes `PRICE_REVIEW.json` before any fit. Source
verification confirms faithful input/import; it does not resolve the 134
development hours flagged for venue-price disagreements. Those flagged closes
are explicitly recorded as unresolved and withheld wherever a feature, target,
portfolio mark or simulated fill requires them. Raw price files are unchanged.
The ledger records source-switching counts and the unchanged conversion priority.
It does not inspect subsequent returns or OOS numeric fields. This is a
conservative eligibility disposition, not a conclusion that flagged prices
were wrong. Both later model comparisons must use this same frozen ledger.

`check` reports eligibility without fitting or writing results. `freeze` pins
code, specification, documentation and price sources before fitting. `run`
requires that freeze and refuses to overwrite results; `run --verify` compares
recomputed artifacts byte for byte. Outputs live separately in
`docs/models/xmr_hourly_price_baseline_v1/`. No command evaluates reserved OOS.
The earlier historical inspection disclosure remains mandatory. This baseline
does not establish whether incidents add information. Later incident comparisons
must restrict both models to identical eligible rows and retain a common hurdle.

## Earlier Kraken-only readiness check

The local read-only check found 7,001 feature-eligible hours and 6,603 labeled
development rows under the unchanged quality settings. Initial selection's
three validation blocks have 6, 2 and 0 rows respectively. Thus the specified
initial selection cannot run on these snapshots. The script reports
`initial_selection_ready: false` and stops rather than skipping an empty fold,
relaxing freshness, moving boundaries, or inspecting outer/OOS outcomes to
choose a replacement. Even the nonempty early blocks are extremely sparse.
A documented pre-run revision or suitable source data is needed before a real
training run with that earlier input. The combined-price addition supersedes
the input choice, while retaining the quality rules and dates. The synthetic
end-to-end test validates training, selection,
metrics and exact reproduction without fitting the real dataset.
