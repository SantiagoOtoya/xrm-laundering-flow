# Hourly XMR incident trading forecast

Date: 2026-10-04. Status: amended specification for a **retrospective catalog-date incident experiment**, accepting the existing 588-row catalog. This amendment replaces the historical reporting-availability and coverage requirements throughout this document. It changes only this file; no code, configuration, dataset, freeze manifest, training result, or Git remote is changed.

The price-only baseline has already been trained and its outer development scores inspected. Its **3% descriptive fallback hurdle remains fixed** for the incident comparison. This amendment was made after that inspection to accommodate the available incident data; it must not be presented as a protocol frozen before those scores were seen. The original numerical defaults remain unchanged unless explicitly revised below.

## Objective and scope

Test whether catalog-derived incident presence, reported magnitude and recency add predictive association with a meaningful five-day XMR/USD gain beyond preceding XMR and BTC price behavior.

**Retrospective hypothesis:** Incident features reconstructed from the catalog's assigned dates and frozen reported USD losses improve forecasts of `P(five-day XMR return > 0.03)` relative to the five-feature price-only model on identical rows. This experiment does not establish that the incident information was available to a trader at the assigned time.

Use hourly UTC observations across price-eligible catalog-incident and catalog-ordinary periods, with a small L2-regularized logistic regression. XMR is bought outright; BTC is an explanatory input, without a BTC position or hedge. The primary research product is a retrospective probability comparison. The fixed paper simulation is an economic diagnostic; the common return hurdle has already been frozen by the price-only run.

This version excludes continuous-return regression, causal-effect claims, minute-level decisions, additional horizon searches, neural networks, and live order placement. Previous event-only model results do not measure this new design's performance. All work described here remains local until separately requested; this document is not an instruction to commit or push.

## Observation and binary target

One observation is one eligible hourly decision time `t`. Define `P_A(t)` as the close of asset A's completed candle covering `[t - 1 hour, t)`, subject to the price-quality rules below. **Price predictors remain past-only and available by t.** The incident predictors are explicitly retrospective catalog proxies and are not certified as available by t. A candle stamped with its starting hour cannot contribute its completed close, high, low, or volume before that hour ends.

```text
R_5d(t) = P_XMR(t + 120 hours) / P_XMR(t) - 1
y_h(t)  = 1 when R_5d(t) > h; otherwise 0
p_h(t)  = estimated P(R_5d(t) > h | past price features, catalog incident proxies)
h       = 0.03, the already frozen descriptive fallback
```

Equality belongs to class 0. Class 0 includes small gains, flat prices, and losses; it does not mean every outcome was negative. Each hourly row starts its own future 120-hour window. The target is not anchored permanently to the incident's occurrence time. BTC-adjusted returns and future BTC returns are not used to construct the target.

The price proxies describe historical returns. A forecast of 0.65 estimates a 65% chance of exceeding the selected hurdle; it does not estimate expected profit, loss severity, or an incident's probability of occurring.

## Fixed cost estimate and candidate hurdles

Use a **2.00% round-trip cost approximation**, charged against the initial trade notional:

| Component | Per side | Round trip |
| --- | ---: | ---: |
| Taker trading fee assumption | 0.80% | 1.60% |
| Combined spread and slippage allowance | 0.20% | 0.40% |
| Total | 1.00% | 2.00% |

The fee assumption is anchored to Kraken Pro's published lowest-volume spot taker tier checked on 2026-10-04. The friction allowance is a planning estimate, not a measurement from our candles or historical order books. This constant scenario is applied throughout the experiment; it does not reconstruct historical fee tiers, establish the user's account tier, or model size-dependent execution. Do not assume maker fills. Source: [Kraken fee schedule](https://www.kraken.com/features/fee-schedule).

For the paper simulation, define `R_net = R_5d - 0.0200`. This is an additive cost approximation on initial notional, rather than exact fee compounding. Do not subtract costs twice: classification uses gross `R_5d > h`; economic evaluation subtracts costs once.

The completed price-only run evaluated **3%, 4%, and 5%** within initial development A. None met the ten-trade activity requirement, so it froze the declared **3% fallback** before outer scoring. Under the 2% additive cost scenario, a gross return above 3% corresponds to a gain above approximately 1% after costs; this is not a selected optimum or evidence of profitability. The incident experiment retains **h = 0.03** for both models and does not repeat or expand hurdle selection after seeing the price-only outer scores.

The return hurdle `h` and probability entry threshold `q` are different: `h` defines the label; `q` decides whether the paper policy enters a trade. Changing a return hurdle changes the prediction problem and class prevalence. Never choose a hurdle merely because its raw accuracy or log loss is best across different labels.

## Feature space: eight inputs

All returns below are log returns. There is no separate seven-day return column: for either asset, `r_7d = r_latest_24h + r_preceding_6d` exactly.

| # | Feature | Definition |
| --- | --- | --- |
| 1 | `xmr_return_24h` | `log(P_XMR(t) / P_XMR(t - 24h))` |
| 2 | `xmr_return_preceding_6d` | `log(P_XMR(t - 24h) / P_XMR(t - 168h))`; the 144 hours before the latest day |
| 3 | `btc_return_24h` | `log(P_BTC(t) / P_BTC(t - 24h))` |
| 4 | `btc_return_preceding_6d` | `log(P_BTC(t - 24h) / P_BTC(t - 168h))` |
| 5 | `xmr_realized_volatility_24h` | Square root of the sum of squared hourly log returns over `[t - 24h, t]`; unannualized |
| 6 | `incident_present_24h` | 1 if a qualifying catalog incident's assumed activation `a_i` lies in `(t - 24h, t]`; otherwise 0 |
| 7 | `incident_catalog_loss_log` | `log(1 + L_i / 1,000,000)`, using the selected active incident's frozen `reported_loss_usd`; otherwise 0 |
| 8 | `incident_age_hours` | `(t - a_i)` in hours for that same selected incident; otherwise 0 |

Here `a_i` is **00:00 UTC on the calendar day after the assigned `incident_date`**, and `L_i` is the catalog's frozen reported USD amount. For example, a catalog date of 2021-02-05 activates at 2021-02-06 00:00 UTC. This is an assumed next-day alignment, not a verified report time, original timezone conversion or guarantee that the information was then public. Age is measured from this assumed activation, not the attack itself. Keep assigned dates, IDs, flags and timing assumptions in the audit, not as extra numerical predictors. Presence distinguishes age 0 at activation from ordinary hours.

`incident_catalog_loss_log` replaces the earlier `incident_known_loss_log` name and meaning. A future implementation must use the new feature definition explicitly; do not populate missing known-at-detection fields or present the catalog amount as contemporaneous information.

The initial model is additive in log-odds, with eight coefficients and an intercept. No interaction expansion is included. Volume, hour-of-day, additional lookbacks, BTC volatility, and alternative incident durations are outside the initial feature search. Price predictors can contain a reaction that occurred before t, but uncertain catalog timing cannot identify the first reaction. This experiment measures predictive association under the stated proxies, not a causal response or a verified real-time information advantage.

## Incident qualification and alignment

Use the current frozen [588-row incident catalog](/Users/c/Documents/Signal/data/curated/incidents_over_1m.csv) **as the incident input**, without requiring reconstruction of historical reporting feeds.

- Qualify an incident using its frozen `reported_loss_usd > 5000000`, strictly. This is a **retrospective reported amount**, not verified gross theft or loss known at activation. Keep the fixed 24-hour active window and 120-hour forecast horizon.
- Preserve each existing `incident_id` and assigned `incident_date`. Do not replace the date with the minimum source date, a publication candidate or an invented precise attack time. Date disagreements and unknown publication time do not disqualify an otherwise structurally valid catalog record.
- Interpret the assigned date as a calendar label for this experiment, with assumed activation at **00:00 UTC the following day**. At hourly t, an incident is active exactly when `t - 24h < a_i <= t`. The next-day convention delays alignment relative to the catalog day but does not prove reporting availability.
- Use the one frozen `reported_loss_usd` value for that incident during its window. Source-loss disagreements, unknown original loss, later revisions and unknown economic basis remain disclosed metadata; they no longer block this retrospective run. Do not sum source claims or infer a historical revision sequence.
- With multiple active qualifying catalog incidents, select the largest individual catalog amount; break ties by earlier assumed activation, then `incident_id`. Presence, magnitude and age must refer to the same selected incident.
- When no qualifying catalog incident is active, set presence, magnitude and age to **0**. This means **no qualifying entry in this frozen catalog window**, not verified absence of attacks or reports. Treat catalog coverage as a modeling assumption; missing historical source-coverage evidence does not exclude ordinary hours.
- Keep the existing canonical grouping and review flags. Repeated source reports are not extra incidents and do not restart activation. Unresolved duplicate pairs remain provisional catalog groups and must be disclosed, not described as independently verified attacks. Do not silently merge or multiply IDs.
- Keep unavailable verified-publication, detection and original-loss fields blank. Historical receipts, original article versions, exact hours, timezones and complete reporting coverage are **not readiness requirements for this mode**. The separate information ledger remains audit context.
- Before fitting, require unique nonempty IDs, valid assigned calendar dates, and finite positive catalog USD amounts. A malformed required field fails the structural check and needs an explicit documented disposition; do not silently turn it into a nonincident example. The current audit found all 588 rows populated with valid dates and amounts.

The USD 5 million threshold, next-day activation, 24-hour duration and maximum-loss aggregation are fixed for this amendment. Do not tune date offsets, replace source dates or change magnitudes using model scores. Expanding to the USD 1 million catalog scope requires a separately declared experiment.

**Limitation:** Retrospective dates and eventual losses can introduce look-ahead information and reporting-selection bias. Delaying activation by one day does not eliminate either. Neither forecast scores nor the paper simulation establish a deployable incident-alert strategy.

## Datasets and readiness

Join XMR and BTC by UTC time into the same observation. Do not stack the two assets as separate training populations. Keep source prices, incident evidence, model inputs, and outcome labels distinguishable.

| Dataset | Purpose | Current position |
| --- | --- | --- |
| [Combined hourly XMR/USD prices](/Users/c/Documents/Signal/data/analysis/xmr_usd_btc_combined_1h.csv) | XMR features, return proxies, and target using `close_usd` | Same combined snapshot used by the completed baseline |
| [Hourly BTC prices](/Users/c/Documents/Signal/data/analysis/btc_usd_1h.csv) | BTC context features | Snapshot exists; user's collection remains ongoing |
| [Historical incident catalog](/Users/c/Documents/Signal/data/curated/incidents_over_1m.csv) | Retrospective incident dates, IDs and reported USD losses | All 588 rows pass the date/amount audit; verified reporting-history fields are not required |
| [Prospective logger specification](/Users/c/Documents/Signal/docs/INCIDENT_LOGGER.md) | Future verified availability and revision history | Separate future work; does not gate this catalog-date experiment |
| Joined hourly modeling frame | Features, labels, split membership, and provenance | Not created by this document |
| Eligibility/exclusion ledger | Missing prices, freshness, incident uncertainty, and censored outcomes | Required before fitting |

The current price snapshots span **2017-01-02 00:00 UTC to 2026-10-03 00:00 UTC, exclusive**:

| Coverage | XMR | BTC |
| --- | ---: | ---: |
| Calendar hours | 85,464 | 85,464 |
| Observed hours | 84,399 | 85,382 |
| Empty hours | 1,065 | 82 |

These figures describe the unchanged combined XMR and Kraken BTC snapshots before model eligibility filtering. The combined XMR column uses per-minute Kraken-first observations with same-minute Binance/BTC conversion fills, as specified in the price-file addition below. It is not an executable cross-venue USD fill. Model counts are smaller after joining, lookbacks, price gates, outcome censoring and purging.

Price-quality defaults: do not forward fill. Require finite positive prices at every required return endpoint; require 25 consecutive valid XMR boundary prices for the 24 hourly volatility returns. A required proxy is considered stale when the existing `close_age_seconds` exceeds 300 seconds. Apply the same freshness limit to target endpoints and report its exclusions. Fewer than 60 recorded minutes is not itself an exclusion. Historical minute-start timestamps do not establish exact last-trade times or live feed receipt latency. Quality settings are frozen without examining their return outcomes.

The incident catalog contains **588 rows, all with day-level date precision and populated reported USD amounts**. The existing audit found 155 incidents with source-date disagreements, and only 41 groups with located publication-time candidates in the separate ledger. Zero rows have verified detection availability or loss known at detection. These limitations are retained and disclosed, but **no longer block the catalog-date experiment**. The catalog has 302 reported amounts strictly above USD 5 million across the full snapshot; that is not the number of independent training rows or price-eligible active windows.

Readiness now requires structurally valid catalog fields, verified unchanged price snapshots, and nonempty chronological training/validation samples under the retained price-quality and 120-hour purge rules. Each training sample must support the binary fit; constant incident columns are reported and scaled using the existing scale-1 convention, rather than discarding all ordinary hours. There is no requirement to verify historical source coverage or recover precise publication times. Actual joined counts must be checked before fitting. Do not move selection or reserved boundaries to compensate for missing prices.

## Data splitting: preserve the latest 20% for OOS

Use **calendar time**, not random rows or class-stratified splits. Freeze the source-history boundaries before filtering eligible model rows. Reserve the most recent 20% of calendar history, rounded upward to a full UTC day. For the current 3,561-day history, this is 713 days, slightly above 20%.

| Stage | UTC start, inclusive | UTC end, exclusive | Calendar hours | Purpose |
| --- | --- | --- | ---: | --- |
| Initial development A | 2017-01-02 00:00 | 2020-11-26 00:00 | 34,176 | Initial training and hurdle selection; first half of development |
| Outer test 1 | 2020-11-26 00:00 | 2022-03-15 16:00 | 11,392 | First chronological evaluation |
| Outer test 2 | 2022-03-15 16:00 | 2023-07-03 08:00 | 11,392 | Second chronological evaluation |
| Outer test 3 | 2023-07-03 08:00 | 2024-10-20 00:00 | 11,392 | Third chronological evaluation |
| **Reserved OOS** | **2024-10-20 00:00** | **2026-10-03 00:00** | **17,112** | **Excluded from all development and selection** |

Development totals 68,352 calendar hours. A occupies half of development, approximately 40% of total history. The remaining development half supplies the three outer tests. These are calendar allocations before eligibility exclusions, not promised training counts. The fractional-day outer boundaries deliberately make the hourly blocks equal in duration.

The existing cutoff is also consistent with the repository's recorded Gator Quant Hacks rule: reserve the shorter of the latest 20% and two years. This window is shorter than two years. The explicit 20% reservation remains the working requirement. See [recorded rule provenance](/Users/c/Documents/Signal/docs/models/xmr_outright_nested_v2/RULE_SOURCE.json).

**Prior inspection disclosure:** Historical reserved-period outcomes were inspected earlier in the project. Deleting those evaluations cannot restore an untouched historical holdout. The interval remains excluded from this model's development; any eventual score must disclose that history. Stronger independent confirmation requires future observations collected after a full policy freeze.

**Amendment timing disclosure:** The price-only outer development scores have also been inspected before this catalog-date amendment. Retain the chronological outer blocks for a paired, exploratory retrospective comparison; do not describe this revised experiment as prospectively specified independent evidence. The same 3% target, numerical grids, price eligibility and paper policy remain fixed. No new reserved-period outcomes were scored in the completed baseline run.

BTC collection may change the source snapshot, but it must not silently move reserved rows into development. Any changed history boundary requires a documented replacement freeze before model outcomes are inspected.

## Initial hurdle selection: completed price-only procedure

**Historical reference only:** This procedure has already selected the declared 3% fallback. Do not repeat hurdle selection for the catalog-date incident model. Preserve the existing [SELECTED.json](/Users/c/Documents/Signal/docs/models/xmr_hourly_price_baseline_v1/SELECTED.json) and use its 3% target for both models.

The original procedure divided A chronologically into an initial training half and three subsequent equal-duration validation blocks. Training expands from the fixed history start:

| Selection fold | Training cutoff | Validation end, exclusive |
| --- | --- | --- |
| 1 | 2018-12-15 00:00 UTC | 2019-08-09 08:00 UTC |
| 2 | 2019-08-09 08:00 UTC | 2020-04-02 16:00 UTC |
| 3 | 2020-04-02 16:00 UTC | 2020-11-26 00:00 UTC |

Each validation block starts at its training cutoff. For each candidate hurdle, fit only on earlier eligible rows and obtain predictions for these future blocks, using five-day purging and training-only scaling. For that hurdle, choose L2 from `{0.01, 0.1, 1.0}` by pooled validation log loss; exact ties prefer stronger L2. These values refer to the explicit mean-loss objective below, not directly to a library's `C` parameter.

Compare hurdle candidates with their selected L2 using the following fixed paper policy:

- Enter outright XMR when flat and `p_h(t) >= 0.60`; this probability threshold is a fixed research assumption and is not tuned.
- Allocate 10% of current portfolio equity as initial XMR notional. Hold the remaining cash without interest. Allow one open position, without leverage, shorting, or stacking hourly forecasts.
- Exit after 120 hours; no stop-loss, take-profit, early exit, or same-timestamp re-entry. Start each validation block flat and end flat. Do not initiate a position whose scheduled exit crosses the block's end.
- Use the completed-hour close proxies and the fixed 2% additive cost model. This simulation is an approximation, not proof of available historical fills or execution capacity.
- Entry eligibility uses information available at entry. If a scheduled exit has no valid price, retain the trade as unresolved rather than retroactively erasing it. A candidate with unresolved trades cannot receive a complete economic selection score.

Select the hurdle with the highest **mean daily log portfolio return across the three validation blocks**, subject to at least 10 completed trades pooled across those blocks and no block exceeding 10% maximum portfolio drawdown. These risk and activity constraints are fixed research defaults. Exact ties prefer the lower hurdle. Report fold returns, drawdowns, trade counts, and incident-associated entries alongside the selection score.

If no candidate satisfies the requirements, record **no economically supported hurdle**. Use a predeclared 3% fallback only for descriptive forecasting evaluation, explicitly labeled as a fallback rather than an optimum; do not claim a tradable edge. Do not expand the grid after seeing failures. The selection folds are tuning evidence, not independent performance evidence.

The original price-only run froze the 3% hurdle and its policy **before its outer tests were scored**. For the amended incident comparison, retain that hurdle and policy, and freeze the new catalog mapping before any incident model fit. This later amendment does not retrospectively become a pre-score specification. All paired metrics use the same 3% target definition.

## Outer evaluation and regularization

For outer test 1, train using A. For test 2, expand training to include the earlier test-1 period once its labels have matured. For test 3, likewise include earlier periods. Reusing earlier observations in a later chronological training window is allowed by the declared expanding procedure; earlier scores cannot influence discretionary changes.

At each outer fit, keep the hurdle fixed and select L2 solely through three expanding inner folds within that outer training span: first half for initial training, remaining half split into three equal calendar validation blocks. Select by pooled inner log loss and refit on all eligible outer-training rows. Scalers are refitted within each individual training sample. Do this independently for each model comparison. Do not reuse a scaler fitted on all development data during evaluation.

No outer score selects features, hurdles, regularization grids, incident thresholds, duration, probability thresholds, cost assumptions, or allocation. Any score-driven redesign makes those evaluated periods development evidence for that redesign; do not continue calling them independent tests.

## Five-day boundary purging

For a training cutoff B, retain a training row only when `t < B`, `t + 120 hours <= B`, and its full target is available by B. Remove rows whose label interval crosses into the next evaluation block. For a validation/test block `[B, E)`, require `B <= t < E` and `t + 120 hours <= E`; labels cannot spill into the next block or reserved OOS history.

Use actual UTC timestamps, not a fixed count of 120 retained rows: missing hours can make those quantities differ. For example, a June 28 training row needs a July 3 price and must be removed when testing begins July 1. Apply this rule at every selection, inner-validation, outer-test, and final development/OOS boundary.

Boundary prices `P_A(B)` refer to the candle ending at B, so they contain no trades after B. A label ending exactly at B is permissible only if that completed price and the label are available by the training cutoff; later data arrival requires exclusion. Past-only feature lookbacks can extend into the preceding training period. They do not require deleting another seven days from the start of every evaluation block.

## Fitting and probability assessment

Use the following objective, with an unpenalized intercept:

```text
p(t) = sigmoid(intercept + beta dot scaled_features(t))
loss = mean_binary_cross_entropy(y, p) + (lambda / 2) * sum(beta ** 2)
```

Fit feature means and standard deviations only on the relevant training rows; standardize all eight inputs, including the presence flag, to make the penalty operate on a declared common scale. Use scale 1 for a zero-variance training column and report it. Verify numerical convergence. Use natural hourly prevalence without incident oversampling or automatic class balancing.

Compare on identical eligible rows, frozen hurdle, and folds:

| Comparison | Inputs |
| --- | --- |
| Training-prevalence benchmark | Constant probability estimated from that training sample |
| Market baseline | Features 1-5 |
| Presence model | Features 1-6 |
| Full incident model | Features 1-8 |

Report **log loss, Brier score, AUC, and accuracy** for each outer block, plus pooled probability scores and class counts. Accuracy uses a fixed 0.50 classification cutoff; the paper entry rule uses 0.60. Report calibration curves and prediction distributions. Brier/log loss assess more than calibration alone. AUC is undefined for a one-class evaluation group and must be reported as unavailable, not invented.

Break out active-incident and ordinary hours and count distinct incident identities. Report net paper-policy return, maximum drawdown, time invested, completed/unresolved trades, and the same policy's market-only comparison. A buy-and-hold XMR benchmark uses the same calendar blocks and cost assumptions; disclose its different exposure. Report a nontrading cash benchmark as well.

Neighboring hourly five-day labels share 119 of 120 hourly return intervals. Do not treat the calendar row count or repeated incident hours as independent trials. Use time-block uncertainty estimates with blocks of at least 120 hours, document the chosen block length, and summarize dependence by distinct incidents and overlapping incident windows. Do not use random row splits or naive independent-row confidence intervals.

## Final fit, OOS, and delivery boundaries

After the declared outer evaluation, apply the unchanged inner-L2 selection procedure to all eligible development history, keep the previously frozen hurdle, and refit once. Preserve all target-end purges at 2024-10-20. Freeze fitted coefficients, scaler, selected L2, source/code hashes, data-quality policy, and the paper policy before any reserved score is calculated.

The reserved latest 20% is not used for fitting, scaling, selection, threshold exploration, or feature analysis. Any later OOS evaluation uses the frozen model and policy without retraining on OOS labels, requires complete 120-hour outcomes inside the reserved period, and reports the earlier-inspection disclosure. Do not iterate on its results. Data after the snapshot end requires a separately frozen prospective plan.

Before a new amended run, verify the same hourly price snapshots and the catalog's structural fields; freeze the exact catalog/price hashes, assumed activation, reported-loss mapping, catalog-absence convention and retained model settings. Produce an exclusion/audit ledger and check paired row membership. **Historical point-in-time reporting coverage is not required.** The prior price-only run already established a 3% fallback, model counts and development scores; this amendment creates no new training result or profitable strategy.

Preserve the existing price-only model/results and manifests. Their pre-run manifest pins the earlier NEWMODELS.MD SHA-256 `0b179ca82361c0027555c583144e612849dbb31f60bd234da4a4fbe63a12814e`. This edit changes that checksum intentionally; do not rewrite an old manifest to pretend it covers the amendment. Any future amended run requires its own specification/code freeze and separate run identity/output location. The old verifier may reject the changed document; that is provenance protection, not a reason to alter archived results.

This task writes **only `NEWMODELS.MD`**. It does not modify existing datasets or model runs, stage or commit changes, push to any branch, or deploy trading software.

## Method references

- [Temporal cross-validation](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html): chronological expanding evaluation; this specification adds timestamp-based target purging.
- [Nested versus non-nested validation](https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html): selection scores and outer evaluation serve different purposes.
- [Probability calibration](https://scikit-learn.org/stable/modules/calibration.html): reliability assessment alongside proper probability scores.
- [XMR hourly schema](/Users/c/Documents/Signal/docs/XMR_HOURLY_PRICES.md) and [BTC hourly schema](/Users/c/Documents/Signal/docs/BTC_HOURLY_PRICES.md): source timing, aggregation, and sparse-price limitations.

## Addition: exact data and rules for the two forecast models

Added 2026-10-04 following the combined-price audit. This addition supersedes
the earlier choice of the original Kraken-only XMR training series and the
same-close paper fill assumption. It records the intended protocol; it does
not change code/configuration, certify unresolved evidence, freeze files, or
authorize training, OOS evaluation, a commit, or a push.

### Price files used by both models

| Asset / purpose | Exact file and field |
| --- | --- |
| XMR/USD features and forecast target | [data/analysis/xmr_usd_btc_combined_1h.csv](/Users/c/Documents/Signal/data/analysis/xmr_usd_btc_combined_1h.csv), `close_usd` |
| BTC/USD explanatory features | [data/analysis/btc_usd_1h.csv](/Users/c/Documents/Signal/data/analysis/btc_usd_1h.csv), `close_usd` |
| Original observed Kraken XMR/USD reference and venue-specific execution analysis | [data/analysis/xmr_usd_1h.csv](/Users/c/Documents/Signal/data/analysis/xmr_usd_1h.csv), `close_usd`; not the primary XMR forecast-training series |

The combined XMR file preserves a traded Kraken XMR/USD minute close when
present; otherwise it uses a traded Binance XMR/BTC close multiplied by a
Kraken BTC/USD close from the **same UTC minute**. The selected hourly close
is the last available such observation inside that hour. It does not carry
prices across missing minutes. Preserve `close_usd_source`,
`close_usd_minute_utc`, `close_age_seconds`, `close_uses_usd_proxy`,
`close_source_changed_from_prior_hour`, and `needs_price_review` as audit
metadata, not additional regression predictors. Minute alignment does not
establish simultaneous trade ticks or an executable cross-venue USD fill.

Use the converted `close_usd`, rather than raw `close_xmr_btc`, for both XMR
features and labels. The target remains outright **XMR/USD** performance:
`y_h(t) = 1[P_XMR(t + 120h) / P_XMR(t) - 1 > h]`. Equality is class 0.
BTC has no hedge position and its future return is absent from the label.
Join XMR and BTC on the same UTC decision grid; do not stack the assets as
separate observations. Full candles stamped at their starting hour become
available after that hour ends, so `P_A(t)` uses the completed prior candle.

### Exact predictors

| # | Feature | Price-only baseline | Full incident model |
| --- | --- | --- | --- |
| 1 | `xmr_return_24h = log(P_XMR(t) / P_XMR(t - 24h))` | Yes | Yes |
| 2 | `xmr_return_preceding_6d = log(P_XMR(t - 24h) / P_XMR(t - 168h))` | Yes | Yes |
| 3 | `btc_return_24h = log(P_BTC(t) / P_BTC(t - 24h))` | Yes | Yes |
| 4 | `btc_return_preceding_6d = log(P_BTC(t - 24h) / P_BTC(t - 168h))` | Yes | Yes |
| 5 | `xmr_realized_volatility_24h`, square root of the sum of 24 squared hourly XMR log returns | Yes | Yes |
| 6 | `incident_present_24h` | No | Yes |
| 7 | `incident_catalog_loss_log = log(1 + reported_loss_usd / 1000000)` for the selected active catalog incident | No | Yes |
| 8 | `incident_age_hours` for the same selected incident | No | Yes |

Thus the models have **five and eight predictors**, respectively, each with
an unpenalized intercept. The denser price dataset increases eligible hourly
observations; it does not add predictors or independent attacks. There is no
extra seven-day column: latest-day return plus preceding-six-day return is
the seven-day log return.

### Retained price-quality rules and source review

- Keep the **300-second maximum recorded-close age** for both assets at every
  required feature endpoint and XMR target endpoint. This is hour end minus
  the selected minute's start, not an exact last-trade timestamp.
- Require finite positive prices. XMR volatility needs **25 consecutive valid
  hourly boundary prices**. XMR return endpoints are `t`, `t - 24h`, and
  `t - 168h`; BTC needs those same three endpoints. No future BTC quality
  observation gates the XMR target.
- Keep empty hours blank; no forward filling, backward filling, interpolation,
  or invented fresh prices. Fewer than 60 traded minutes within an hour is
  not itself a reason to reject it.
- Resolve flagged prints and source disagreements using source evidence,
  without choosing a treatment from model scores or subsequent price returns.
  `needs_price_review` is a review flag, not proof that the selected close is
  invalid. Before freezing, log an accepted/invalid/unresolved disposition;
  invalid or unresolved required prices cannot silently enter the model.
  Apply the frozen disposition consistently to both models and retain an
  exclusion ledger. Review source switching as a possible contributor to
  measured momentum and volatility.

The read-only development audit, **before additional price-review exclusions**,
found 52,479 labeled price-eligible rows with the combined XMR series and the
unchanged five-minute rules, compared with 6,603 using Kraken alone: 45,876
additional rows. Initial selection validation blocks contained 5,016, 5,248,
and 5,350 rows. These are opportunity counts, not training results, guaranteed
final counts, or independent samples. The audit identified 35,371 development
closes using the conversion proxy and 134 hours needing price review.

### Incident files and retrospective catalog eligibility

This catalog-date amendment **supersedes the earlier verified reporting-history gate**, including the former readiness requirement near line 107. Only the incident model receives the three incident predictors.

Use [data/curated/incidents_over_1m.csv](/Users/c/Documents/Signal/data/curated/incidents_over_1m.csv) directly:

- `incident_id` supplies the existing canonical group.
- `incident_date` supplies the assigned day, with assumed activation at **00:00 UTC the following day**.
- `reported_loss_usd` supplies the fixed retrospective USD magnitude and the strict **> USD 5 million** filter.
- Preserve `date_precision`, `source_dates`, loss bounds/basis and review flags as audit metadata, not additional regression predictors.

Do not substitute the earliest source date or a publication candidate for the assigned date. All 588 assigned dates are day-level; none is automatically certified as the first attack or public-report date. Date disagreements and absence of verified availability, original loss or continuous source coverage do not exclude otherwise valid catalog rows or ordinary price hours.

At t, active catalog incidents satisfy `t - 24h < a_i <= t`. Select the largest qualifying individual catalog amount; break ties by earlier assumed activation, then ID. Use that same incident's age. With no active qualifying catalog entry, set all three incident inputs to zero. This explicitly assumes the frozen catalog is the reference population for ordinary hours; it is not evidence of globally complete reporting.

The separate [reports ledger](/Users/c/Documents/Signal/data/curated/incident_information_v1/reports.jsonl), [source coverage](/Users/c/Documents/Signal/data/curated/incident_information_v1/source_coverage.json), [readiness ledger](/Users/c/Documents/Signal/data/curated/incident_information_v1/readiness.json), [duplicate reviews](/Users/c/Documents/Signal/data/curated/incident_information_v1/duplicate_pair_reviews.json), and [identity crosswalk](/Users/c/Documents/Signal/docs/dedup/baseline_crosswalk.csv) remain provenance/audit resources. Their missing historical fields do not gate this mode. No ledger is modified or falsely upgraded to verified status.

Existing IDs and grouping are retained, including disclosed provisional identity pairs. Do not count repeated source reports as distinct incidents, sum duplicate losses or claim all catalog groups are independently verified attacks. Freeze all mappings before fitting. Retrospective magnitude and uncertain date assignment can create look-ahead information; assumed next-day activation does not remove that limitation.

### Training populations, tuning, splits and freeze

The standalone price baseline uses price-eligible development hours without incident inputs. For the retrospective incident comparison, use **identical price-eligible rows, target labels and calendar blocks for both models**, with structurally valid catalog-derived states. Ordinary hours are usable without verified reporting coverage. Apply any genuine structural incident exclusions consistently to both models and record them; metadata uncertainties accepted above do not exclude rows.

Reuse the saved baseline predictions only if exact row membership, target and fold training populations match. Otherwise refit the price-only comparator on the shared population using the same prescribed inner selection. Do not compare scores from different subsets. Price eligibility itself is unchanged by this incident-data amendment.

Retain the existing calendar boundaries: history starts 2017-01-02 00:00 UTC;
initial A ends 2020-11-26 00:00 UTC; outer blocks end 2022-03-15 16:00 UTC,
2023-07-03 08:00 UTC, and 2024-10-20 00:00 UTC. The latest 20%,
**2024-10-20 00:00 UTC through 2026-10-03 00:00 UTC exclusive**, remains
reserved. Quality filtering does not move these dates. Keep timestamp-based
120-hour target purging at every selection, inner, outer and OOS boundary.
Do not move these boundaries or use outer/OOS results to tune the catalog mapping. Unknown reporting coverage no longer blocks this retrospective mode; an infeasible price sample still requires an explicit specification revision.

Use the **already frozen common 3% fallback hurdle** for both models. The original price-only 3%/4%/5% search stays recorded as tuning evidence; the incident model does not select a new hurdle. Each model separately selects L2 from 0.01, 0.1 and 1.0 inside its own chronological training folds. Fit all scaler parameters on each fold's training rows only. Preserve mean binary cross entropy plus `lambda/2 * sum(beta**2)`, natural prevalence, no class balancing and an unpenalized intercept. Outer scores select none of these settings.

Retain the fixed 0.60 paper entry probability, 10% equity notional, one long
position, 120-hour holding period, and 2% round-trip additive cost scenario.
For research-proxy simulations, execute at the **next completed hourly close**,
one hour after the signal, and hold 120 hours from that fill. Forecast labels
keep their completed-close decision clock, so the simulation's return and
label return can differ. Do not gate entries using future endpoint validity;
missing scheduled exits remain unresolved. A venue-specific execution
evaluation must use prices and costs from the actual proposed venue. Converted
cross-venue research prices do not establish available Kraken fills. Include
double-cost stress and disclose benchmark exposure differences.

Before any amended fit, freeze exact price/catalog checksums, retained source-selection/conversion and review rules, predictor definitions, assumed next-day activation, retrospective magnitude, catalog-absence convention, eligibility rules, splits, narrow L2 grid, tie rules and paper policy. Reference the existing 3% hurdle-selection freeze without changing it, and record the new final model/scaler freeze before any reserved evaluation. Report log loss, Brier, AUC, accuracy, calibration, probability distributions and prevalence benchmarks on identical rows and calendar blocks. Use the declared 168-hour calendar-block uncertainty procedure, not independent hourly intervals. Preserve both the earlier reserved-outcome inspection and the price-only outer-score-before-amendment disclosures.

**Implementation status:** The completed price-only run used the combined `close_usd` series and one-hour delayed paper fills. The incident script's existing readiness report was produced under the earlier verified reporting-history requirements and found zero eligible rows. This document-only amendment does **not** change that script or its saved readiness report. A future implementation must explicitly support the catalog-date mode and `incident_catalog_loss_log`, preserve the same price inputs/rules, and use a new freeze/run identity before fitting. Do not claim this edit itself unblocks the unchanged runner or creates an incident result.

Only `NEWMODELS.MD` is changed by this task. No other file, training run, stage, commit, push or deployment is authorized by this edit.
