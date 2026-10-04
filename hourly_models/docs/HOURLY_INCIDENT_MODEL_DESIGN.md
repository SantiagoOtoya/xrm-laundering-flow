# Proposed hourly XMR model with incident inputs

Status: design and data-readiness assessment. No expanded model was fitted. The pushed event-only model and frozen runs are unchanged. The historical incident timing mode remains unresolved: verified availability feed versus an explicitly retrospective catalog-date experiment.

## Observation, features and target are different objects

The old run trained on 162 incident-date rows. Each row had three backward-looking price features and one five-day binary label. Five daily outcome returns were combined to calculate that label; they were not five separate training examples. The model was not a sequence model receiving five future price points.

The proposed observation is one eligible hourly decision time, including both incident and nonincident states. XMR and BTC history are aligned into columns on the same row. They are not two independent training populations. The model predicts XMR direction; BTC remains context rather than an asset held in the position.

At decision time t, all predictors must have become available by t. A candle stamped with its opening hour has high, low, close and full volume only after its ending hour. Use completed prior candles. Retain source freshness/coverage metadata and reject missing or stale input rather than inventing prices.

Keep the five-day target for the first experiment:

`y(t) = 1 if XMR_price(t + 120 hours) / XMR_price(t) - 1 > 0, else 0`.

Both prices are predeclared historical boundary proxies subject to quality gates; this is a gross direction target, not a promise of executable fill prices or net profit. Sampling every hour does not shorten the target horizon to one hour.

## Initial feature proposal

| Input | Proposed definition |
| --- | --- |
| XMR momentum | Log-price change over 168 preceding completed hours (seven calendar days) |
| BTC momentum | Same backward-looking 168-hour measure, with matching time boundaries |
| XMR volatility | Standard deviation of returns across 480 preceding completed hours (twenty calendar days); hourly volatility units differ from the old daily-return volatility |
| Incident presence | Indicator that a qualifying unique incident became durably available during the preceding 24 hours; an arbitrary numerical Unix timestamp is not used as a coefficient input |
| Incident magnitude | `log(1 + known_loss_usd / 1,000,000)` for the largest individually reported qualifying incident active in that same 24-hour interval; zero when no qualifying incident is active |

The 24-hour state and maximum-loss aggregation are proposed fixed initial definitions, not optimized choices. Retain the old strict >$5m qualification for the first controlled comparison; expanding to all >$1m catalog incidents would be an additional scope change to specify before fitting. Unknown or disputed loss/scope is not equivalent to zero loss or a verified negative signal. Qualifying events require a known reviewed amount above the threshold; retain unresolved claims in a separate audit ledger.

Deduplicate repeated reports and updates by canonical incident identity. Presence activates once at first qualified acceptance, not every polling observation. A later loss update becomes usable only when that revision becomes available. For multiple attacks, retain each identity and take the largest individual known amount; never sum duplicate reports.

Direct timestamp belongs in the alignment and audit schema: occurrence time, claimed publication time, first receipt time, durable acceptance time, revision time and price time are distinct fields. Presence must be derived from availability, not an attack transaction identified afterward. A separate elapsed-hours-since-acceptance predictor can be considered in a later version if the five-input baseline warrants it. Do not label a row by whether an incident happens later in its outcome window.

## Readiness and coverage

Current hourly XMR coverage: 85,464 calendar hours, 83,919 with observed trades and 1,545 empty hours. The file already exists at `data/analysis/xmr_usd_1h.csv`. It describes the same 2,053,386 retained minute observations. Partial hours are common and must be assessed by timing/quality criteria; requiring all 60 minutes would confuse a sparse trade stream with source invalidity.

BTC minute prices are also retained. A BTC hourly derivation using matching boundaries is needed for the joined frame; the existing daily feature tables cannot supply hourly BTC context. The user's existing hourly builder and outputs were inspected only and not edited during this assessment.

The historical catalog has 588 rows, all with day precision. `detection_available_at_utc` and `loss_known_at_detection_usd` are populated in zero rows. A prior 30-record pilot recovered 23 claimed publication timestamp candidates but verified zero historical detector receipts and zero original content/amount states as of publication. The prospective logger provides receipts going forward; collection today does not establish when a historical catalog claim was available.

An hourly retrospective study using assumed catalog-day activation and final losses can be clearly labeled as such. It cannot be represented as a model trained on verified historical announcement-time information. A timestamped feed or additional source reconstruction is needed for that claim. No arbitrary midnight timestamp is silently substituted for an exact historical receipt.

## Sampling versus information

| Decision frequency | Full-history calendar bins | Bins in a five-day outcome | Overlap between neighboring five-day windows |
| --- | ---: | ---: | ---: |
| Daily | 3,561 | 5 | 4/5 = 80% |
| Hourly | 85,464 | 120 | 119/120 = 99.17% |
| Five minutes | 1,025,568 | 1,440 | 1,439/1,440 = 99.93% |

Counts are calendar opportunities before price, feature and timing exclusions. These are not independent sample counts. Finer data improves alignment, captures intraday context and can support different decision times. It does not multiply the number of unique attacks. Repeated hourly observations after one attack do not become 24 independent experiments.

## Modeling and validation

Start with a regularized logistic model, mean cross-entropy plus explicit L2, and the same narrow candidate range. An 85k-by-five float32 feature matrix uses about 1.7 MB before labels and processing overhead. More rows raise computational cost, not necessarily the required number of parameters. CPU training is a reasonable starting point; no specific runtime or GPU benefit has been measured for the proposed frame. A more complex model is justified only by robust validation gains or an explicit sequence-model objective, not the raw candle count.

Freeze two otherwise comparable candidates: price-only and price-plus-incident inputs. Compare them on identical eligible rows, folds, target and costs assumptions. Retain the natural distribution of incident states for probability evaluation; arbitrary class weighting or oversampling can change probability interpretation and must not silently be introduced. Report log loss, Brier, AUC and accuracy both overall and on incident-associated rows, with dependence-aware uncertainty and incident-cluster summaries. An aggregate result can be dominated by ordinary hours and hide whether incidents add value.

Preserve the external calendar reserve starting 2024-10-20. Of the 85,464 calendar hours, 68,352 precede that boundary and 17,112 belong to the reserved period. All model selection stays inside earlier development. Remove training labels whose 120-hour outcomes cross a validation boundary, and validation labels that cross that fold's ending boundary. Fit scalers only within each training sample; choose L2 through inner temporal validation. Account for repeated incident states and serial dependence rather than random row splits. Existing historical inspection remains disclosed.

Hourly resolution is the recommended initial comparison. Five-minute aggregation is possible from retained minute data, but a five-day forecasting task does not gain 12 times as many independent outcomes by using it. A five-minute experiment is more relevant if the hypothesis specifically concerns a rapid response and the incident availability timestamps and executable market data support that timing. Changing the horizon would be a separate predeclared experiment.

Sources: [hourly price coverage](XMR_HOURLY_PRICES.md), [incident feasibility pilot](pilot/FEASIBILITY_PILOT.md), [lagged-feature forecasting example](https://scikit-learn.org/stable/auto_examples/applications/plot_time_series_lagged_features.html), [temporal validation](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html), [scalable linear classifier documentation](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.SGDClassifier.html).
