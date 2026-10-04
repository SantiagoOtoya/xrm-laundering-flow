# Hypothesis

**Status: Pre-registered specification, written before any result of this model was seen. Changes after this commit are made as new dated commits with a stated reason.**

## Economic hypothesis

**Edge source: structural constraint.**

We expect XMR (Monero) to rise against the US dollar over the five days after a large crypto theft (known loss above $5M) becomes public, because attackers must convert stolen, traceable funds into a privacy coin before exchanges and issuers freeze them, and this buying is forced and largely insensitive to price. The edge persists because launderers cannot skip this step and must act within days of disclosure, while XMR's thin, delisting-reduced liquidity means sellers do not price the incoming flow in advance. If true, hourly forecasts of a meaningful five-day XMR gain should improve when we add whether a qualifying incident was reported in the last 24 hours, its known loss and its age, beyond what recent XMR and BTC returns and XMR volatility already say. It fails if those incident inputs add no predictive value over market features alone, or if the forecast edge does not survive realistic costs.

- **Who is on the other side:** existing XMR holders and market makers who sell into forced, price-insensitive laundering demand without knowing a large conversion is coming.
- **Why it persists:** the demand is compelled (frozen funds are worthless to an attacker), arrives in bursts tied to disclosures, and few arbitrageurs can hold or source XMR at scale after exchange delistings.
- **Testable prediction:** the incident features (6–8 below) improve out-of-fold probability forecasts relative to the market-only baseline (features 1–5), and the fixed paper policy using them does better net of costs than the same policy using the market-only model.
- **What would kill it:** no improvement over the market-only baseline; an improvement that disappears at 2× costs; launderers switching to other routes (for example cross-chain bridges or other privacy coins); or the move being priced in before the hourly decision time.

Formal statement: incident presence, the loss magnitude known at the decision time, and incident recency add predictive value for `P(five-day XMR return > h)` relative to a model using market features alone.

## Specification

### Scope
- Market: XMR/USD spot (Kraken). BTC/USD is an explanatory input only; there is no BTC position or hedge.
- Hourly UTC decisions across eligible incident and non-incident hours.
- Primary output: a probability forecast. A fixed paper-trading policy selects the return hurdle and gives the economic result.
- Out of scope: continuous-return regression, causal-effect claims, minute-level decisions, other horizons, neural networks, live order placement.

### Observation and target
- One observation is one eligible hourly decision time `t`. `P_A(t)` is the close of asset A's completed candle covering `[t − 1h, t)`. A candle cannot contribute its close, high, low or volume before its hour ends.
- `R_5d(t) = P_XMR(t + 120h) / P_XMR(t) − 1`.
- `y_h(t) = 1` when `R_5d(t) > h`, otherwise 0 (equality is class 0). Class 0 includes small gains, flat prices and losses.
- Each hourly row has its own 120-hour window; the target is not anchored to the incident time. BTC-adjusted and future BTC returns are never used in the target.

### Costs
- **100 bps per side, 200 bps round trip**, charged on initial notional: an 80 bps taker fee (Kraken Pro lowest-volume spot taker tier, checked 2026-10-04, https://www.kraken.com/features/fee-schedule) plus a 20 bps spread and slippage allowance per side. The allowance is a planning estimate, not a measurement. No maker fills are assumed.
- `R_net = R_5d − 0.0200` (additive). Classification uses gross `R_5d > h`; economic results subtract costs once.
- *(Added for the track brief; reporting only)*: every economic result is also reported at 2× costs (400 bps round trip). This never feeds into hurdle selection.

### Return hurdles
- Candidate gross hurdles: **3%, 4%, 5%** only (about 1%, 2% and 3% after costs). These are research choices, not optimal values.
- The hurdle `h` defines the label; the entry threshold `q` decides whether the policy trades. They are different.

### Features (eight, log returns)
1. `xmr_return_24h` = `log(P_XMR(t) / P_XMR(t − 24h))`
2. `xmr_return_preceding_6d` = `log(P_XMR(t − 24h) / P_XMR(t − 168h))`
3. `btc_return_24h` = `log(P_BTC(t) / P_BTC(t − 24h))`
4. `btc_return_preceding_6d` = `log(P_BTC(t − 24h) / P_BTC(t − 168h))`
5. `xmr_realized_volatility_24h`: square root of the sum of squared hourly log returns over `[t − 24h, t]`, unannualized
6. `incident_present_24h`: 1 if qualifying incident information first became available in `(t − 24h, t]`, otherwise 0 (within verified coverage)
7. `incident_known_loss_log` = `log(1 + L_i(t) / 1,000,000)` for the selected active incident; 0 if none
8. `incident_age_hours` = `t − a_i` in hours for that incident; 0 if none

The model is additive in log-odds: eight coefficients plus an intercept, with no interactions. Timestamps and incident IDs are kept for auditing and are not predictors. Excluded from the feature set: volume, hour of day, other lookbacks, BTC volatility, other incident windows.

### Incidents
- Threshold: known individual loss **strictly above USD 5,000,000**, using the amount known at `t`, not a later final amount.
- `a_i` is the first time a reviewed qualifying identity and loss claim were durably available. If the amount crosses $5M only in a later revision, qualification starts at that revision's availability time. Later revisions never rewrite past features, and ordinary updates do not restart the clock.
- Identities are canonical across sources; repeated reports do not create new incidents or restart the window.
- With several active incidents, use the largest known individual loss and that incident's age. Ties go to the earlier qualification time, then the canonical ID. Source reports are never summed.
- Unknown, conflicting or unresolved amounts stay unknown. Hours they affect are excluded under a rule frozen before fitting, and the exclusions are logged.
- A presence flag of 0 means no qualifying report came through the defined sources; it does not mean no attack happened. Uncovered periods and source outages count as unknown coverage, not negatives. Initial catalog snapshots and stale backfills are not fresh alerts.
- The 24-hour window, the $5M threshold and the max-loss rule are fixed design choices and are not tuned.

### Data
- Kraken spot hourly bars for XMR/USD and BTC/USD (Kraken OHLCVT archive), joined by UTC hour into one observation, not stacked. *(XMR/USD source: see Amendment 1.)*
- Snapshot: 2017-01-02 00:00 UTC to 2026-10-03 00:00 UTC (exclusive), 85,464 calendar hours.
- Incident catalog: 588 incident groups over $1M, compiled from DefiLlama hacks, SlowMist Hacked, rekt.news and linked primary sources.
- No forward filling. Every return endpoint needs a finite positive price, and the 24 volatility returns need 25 consecutive valid XMR prices.
- A required price is stale when `close_age_seconds` > 300. The same rule applies to target endpoints, and exclusions are reported. Fewer than 60 recorded minutes is not by itself an exclusion.
- A pre-run manifest and an eligibility and exclusion ledger are produced before fitting.

### Fitting
- `p(t) = sigmoid(intercept + β · scaled_features(t))`; loss = mean binary cross-entropy + (λ/2)·Σβ², with the intercept unpenalized.
- All eight inputs are standardized using training rows only (a zero-variance column gets scale 1 and is reported). Natural hourly prevalence is used, with no oversampling or class balancing. Convergence is verified.
- λ ∈ {0.01, 0.1, 1.0}, chosen by pooled validation log loss. Exact ties prefer the stronger λ.

### Five-day purging
- For a training cutoff B, a row is kept only if `t < B`, `t + 120h ≤ B`, and its full target is available by B.
- For an evaluation block `[B, E)`, rows need `B ≤ t < E` and `t + 120h ≤ E`.
- Purging uses actual UTC timestamps, not row counts, and applies at every selection, inner, outer and development/OOS boundary.

## Out-of-sample protection

Track rule: the most recent 20% of history or 2 years, whichever is shorter. 20% of the 3,561-day history is 712.2 days, rounded up to 713 full days. That is shorter than 2 years, so the 20% rule binds and **out-of-sample starts 2024-10-20 00:00 UTC**.

| Stage | UTC start (incl.) | UTC end (excl.) | Hours |
| --- | --- | --- | ---: |
| Initial development A | 2017-01-02 00:00 | 2020-11-26 00:00 | 34,176 |
| Outer test 1 | 2020-11-26 00:00 | 2022-03-15 16:00 | 11,392 |
| Outer test 2 | 2022-03-15 16:00 | 2023-07-03 08:00 | 11,392 |
| Outer test 3 | 2023-07-03 08:00 | 2024-10-20 00:00 | 11,392 |
| **Out-of-sample (run once)** | **2024-10-20 00:00** | **2026-10-03 00:00** | **17,112** |

### Hurdle selection (inside A only)
- Training runs from 2017-01-02 to each cutoff. The validation blocks are [2018-12-15 00:00, 2019-08-09 08:00), [2019-08-09 08:00, 2020-04-02 16:00) and [2020-04-02 16:00, 2020-11-26 00:00).
- For each hurdle, λ is selected by pooled validation log loss, and then the fixed paper policy runs:
  - Buy XMR when flat and `p_h(t) ≥ 0.60`. This threshold is fixed, not tuned.
  - The position is 10% of current equity; the rest sits in cash without interest. One position at a time, with no leverage, shorting or stacking.
  - Exit after 120 hours, with no stop-loss, take-profit, early exit or same-timestamp re-entry. Each block starts and ends flat, and no trade may have its exit after the block end.
  - A missing exit price leaves the trade unresolved, and a hurdle with unresolved trades cannot get a complete score.
- The chosen hurdle has the highest mean daily log portfolio return across the three blocks, with at least 10 completed trades pooled and no block drawdown worse than 10%. Ties prefer the lower hurdle.
- If no hurdle qualifies, the result is recorded as **no economically supported hurdle**. 3% is then used as a labelled fallback for descriptive forecasting only, and no tradable edge is claimed. The grid is not expanded after failures.
- Frozen before any outer test is scored: hurdle, costs, features, eligibility rules, `q`, sizing, exit policy, selection objective, split timestamps, tie rules and fallback rules.

### Outer evaluation
- Expanding window: test 1 trains on A, and tests 2 and 3 add the earlier periods once their labels have matured.
- At each outer fit the hurdle stays fixed. λ is chosen by three expanding inner folds within that training span (first half for training, second half split into three equal blocks), and the model is then refit on all eligible training rows.
- No outer score selects features, hurdles, λ grids, thresholds, durations, costs or sizing. A redesign driven by scores turns those periods into development evidence.

### Final fit and out-of-sample
- After the outer evaluation, the same inner-λ procedure runs on all eligible development history with the frozen hurdle, and the model is refit once. Purges end at 2024-10-20.
- Coefficients, scaler, λ, source and code hashes, the data-quality policy and the paper policy are frozen before any out-of-sample score.
- The out-of-sample period is never used for fitting, scaling, selection, threshold exploration or feature analysis. It is evaluated **once** with the frozen model and policy, needs complete 120-hour outcomes inside the period, and is reported whether good or bad. There is no iteration on it.

## Comparisons (identical rows, hurdle and folds)

| Model | Inputs |
| --- | --- |
| Training-prevalence benchmark | constant probability from the training sample |
| Market baseline | features 1–5 |
| Presence model | features 1–6 |
| Full incident model | features 1–8 |

Economic benchmarks: the same paper policy using the market baseline, buy-and-hold XMR (same blocks and costs, with its different exposure disclosed), and cash.

## Reported metrics (development and out-of-sample separately)
- Forecasts: log loss, Brier score, AUC (reported as unavailable for one-class groups), accuracy at a 0.50 cutoff, class counts, calibration curves and prediction distributions. These are given per outer block and pooled.
- Paper policy: net return, maximum drawdown, time invested, and completed and unresolved trades.
- *(Added for the track brief; reporting only)*: annualized return, annualized volatility, annualized Sharpe ratio, turnover per year and an equity curve, all net of costs and also at 2× costs.
- Breakdowns: active-incident hours vs ordinary hours, and the number of distinct incidents.
- Uncertainty: time-block methods with blocks of at least 120 hours, with the block length documented. Neighbouring hourly labels share 119 of their 120 hours, so rows and repeated incident hours are not independent trials. There are no random splits and no naive confidence intervals.

## Risk and capacity
- Position limits: one open position, sized at 10% of equity, long only, no leverage and a fixed 120-hour exit. The most that can be lost on one trade is 10% of equity plus costs.
- Development drawdown limit: a hurdle is rejected if any validation block draws down more than 10%.
- Capacity is not modelled by the 200 bps constant cost; position size relative to XMR's hourly volume is reported in the note as a limitation.

## Variants tried (to be disclosed in the note)
The planned search is 3 hurdles × 3 λ values, plus 4 model comparisons, inside development only. Any further variant is counted and disclosed.

## Disclosure
- The 588-row incident catalog has day-level dates only, and its point-in-time fields (`detection_available_at_utc`, `loss_known_at_detection_usd`) were empty when this specification was written. Hourly price data alone cannot supply them. How they are filled is documented before fitting.
- If valid incident-information coverage does not support the initial selection period, this protocol cannot be run as specified. Selection is never moved into outer or out-of-sample data to compensate.
- If the price snapshot changes, the split boundaries do not move silently. Any change requires a documented replacement freeze before outcomes are inspected.

## Open items (must be fixed before the freeze)
1. The decision rule for "adds predictive value": which comparison and metric count (for example full vs market baseline on pooled outer log loss), and what significance standard applies.
2. The block length for the time-block uncertainty estimate (at least 120 hours).
3. The exclusion rule for hours affected by unresolved candidate incidents.
4. How `detection_available_at_utc` and `loss_known_at_detection_usd` are filled (sources and rule), and the verified coverage periods.

## References
- Kraken fee schedule: https://www.kraken.com/features/fee-schedule
- Temporal cross-validation: https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html
- Nested vs non-nested validation: https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html
- Probability calibration: https://scikit-learn.org/stable/modules/calibration.html
- López de Prado (2018), *Advances in Financial Machine Learning*: purged cross-validation.

## Amendment 1 (2026-10-04 UTC): price source, incident timing, decision rule

**Reason.** Two parts of the specification could not be run as written. (1) The Data section names Kraken as the only XMR/USD source, but Kraken XMR/USD trades sparsely; the data build and both training scripts use a combined Kraken/Binance hourly close. (2) The incident catalog has day-level dates only, and `detection_available_at_utc` and `loss_known_at_detection_usd` are empty in all 588 rows, so features 6–8 and the test could not be computed. This amendment records the price rule as implemented, fixes the incident rules, and resolves Open items 1–4. It does not change the target definition, features 1–5, costs, hurdles, paper policy, split or out-of-sample rule.

### Price source
- XMR features and targets use `close_usd` from `data/analysis/xmr_usd_btc_combined_1h.csv`.
- Per minute: use the Kraken XMR/USD close when that minute has a Kraken trade. Otherwise use `Binance XMR/BTC close × Kraken BTC/USD close`, only when both have a trade in the **same UTC minute**.
- Hourly close: the last minute in the hour with a price from either source. Binance can therefore set the hourly close even when Kraken traded earlier in that hour.
- Binance zero-trade candles and timing-irregular (quarantined) rows are never used. No price or BTC rate is carried into another minute or hour, so the no-forward-filling rule still holds.
- `close_age_seconds` is the end of the hour minus the selected minute's start. The 300-second staleness rule applies to it unchanged.
- Binance XMR/BTC exists only from 2017-11-10 06:12 UTC to 2024-02-20 02:59 UTC, after which Binance delisted XMR. Outside that window the series is Kraken only.
- BTC features use Kraken BTC/USD only (`data/analysis/btc_usd_1h.csv`).
- Effect, reported in the note: fresh XMR/USD hours go from 83,919 (Kraken only) to 84,399, and empty hours from 1,545 to 1,065 (977 of them in 2017, before Binance coverage). 35,371 hourly closes use the Binance conversion and are labelled (`close_uses_usd_proxy`). The selected source changes between adjacent hours 20,843 times, which can add apparent returns. 134 hours are flagged `needs_price_review`. Across 1,006,922 aligned minutes, the median absolute difference between the venues is 0.10% (95th percentile 0.52%).

### Incident timing and qualification
- **Report date:** `located_report_date` if present, otherwise the latest date in `source_dates`. `incident_date` is never used.
- **Availability time:** `a_i` = 00:00 UTC on the day after the report date. A report made at any time on day D is first usable at D+1 00:00, so there is no within-day lookahead. Up to 24 hours of the first-day reaction is lost; this reduces power, not validity.
- **Qualification:** `reported_loss_usd` > 5,000,000, from the catalog.
- **Coverage:** the catalog is treated as complete for incidents above $5M from 2017-01-02 to 2026-10-03, so hours with no qualifying incident have `incident_present_24h` = 0 throughout.
- **Unresolved amounts:** an hour `t` is excluded, and logged, when an incident with a blank or non-numeric `reported_loss_usd` has `a_i` in `(t − 24h, t]`. With the current catalog this excludes no hours, because every row has an amount.

### Primary and secondary models
- **Primary test: presence model (features 1–6) vs market baseline (features 1–5).** The paper-trading policy and its economic results use the presence model.
- **Secondary, labelled "contains lookahead": full model (features 1–8).** Feature 7 uses final catalog amounts, which were not necessarily known at `t`. Its results are reported but never used for the decision or the policy.

### Decision rule
- Statistic: the mean, over all pooled outer-test rows, of (market-baseline per-row log loss − presence-model per-row log loss). Both models use identical rows, the frozen hurdle and the same folds.
- Inference: circular block bootstrap over contiguous hours, **block length 168 hours**, 10,000 resamples, seed 20261004. One-sided p = share of resamples whose mean difference is ≤ 0.
- **The hypothesis is supported if p < 0.05.** This is a single test, so no multiple-testing correction applies.
- The 168-hour block covers the 120-hour label overlap and the 168-hour lookback of feature 2.

### Limitations recorded before scoring
- Source dates mostly equal the hack date: 271 of the 302 qualifying incidents have an earliest source date on the hack date. An incident disclosed publicly days after it happened would therefore be timed too early, which is lookahead.
- Qualification above $5M uses retrospective amounts (583 of 588 rows have `loss_basis` = retrospective reported amount), so which incidents count is itself partly chosen with hindsight. This affects the presence model as well as the full model.
- Catalog coverage may be incomplete, especially in 2017–2018.
- Only 41 qualifying incidents fall in period A, where the hurdle is selected.

### Disclosure
- This amendment was written after the outer-test scores of the price-only market baseline (features 1–5) had been inspected. Pooled over the three outer tests: log loss 0.637741, Brier 0.222787, AUC 0.543802. No setting in this specification was changed after that inspection.
- No outer-test scores had been viewed for the presence model (features 1–6) or the full model (features 1–8) when this amendment was written.
- The reserved out-of-sample period has not been scored.

### Source
Binance public spot klines, XMRBTC 1-minute monthly files 2017-11 to 2024-02 (76 files), https://data.binance.vision/?prefix=data/spot/monthly/klines/XMRBTC/1m/, each checked against Binance's published checksums.
