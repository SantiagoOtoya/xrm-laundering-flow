# Combined XMR hourly prices from Kraken and Binance

The new `data/analysis/xmr_usd_btc_combined_1h.csv` contains **85,464 UTC hours**
from January 2, 2017 through October 2, 2026. It contains hourly close series for
XMR/USD and XMR/BTC, their original venue series, source choices, observation
ages and gap classifications. It is a separate research series; the existing
Kraken price files and model inputs remain unchanged.

## Improvement in coverage

| Measure | Kraken XMR/USD | Combined XMR/USD |
| --- | ---: | ---: |
| Hours with a fresh price | 83,919 | 84,399 |
| Empty hours | 1,545 | 1,065 |
| Fresh minute observations underlying the hourly closes | 2,053,386 | 3,940,383 |
| Hours with 60 fresh minute observations | 451 | 13,800 |

The combination adds **480 formerly empty hours** and **1,886,997 fresh minute
observations**, a 91.9% increase in the underlying minute count. It retains
84,270 populated hourly XMR/BTC closes, with 1,194 hours unavailable.

| Year | Original empty USD hours | Combined empty USD hours |
| --- | ---: | ---: |
| 2017 | 977 | 977 |
| 2018 | 156 | 54 |
| 2019 | 284 | 4 |
| 2020 | 98 | 2 |
| 2021 | 6 | 6 |
| 2022 | 1 | 0 |
| 2023 | 1 | 1 |
| 2024 | 12 | 11 |
| 2025 | 10 | 10 |
| 2026 through October 2 | 0 | 0 |

**977 of the remaining 1,065 empty USD hours are in 2017.** The supplied Binance
history starts November 10, 2017 at 06:12 UTC and ends February 20, 2024 at 02:59
UTC. It cannot improve the earlier portion of 2017 or extend Binance observations
past its actual ending timestamp.

## Sparse trading versus collection gaps

These categories are separate:

| Observation | Interpretation |
| --- | --- |
| Binance candle with zero trades and zero volume | Explicitly reported no trading on that venue/pair; its repeated price is excluded from fresh observations |
| Binance timestamp absent from the official source within this archive's window | Upstream source gap with unknown cause; it is not assumed to be a zero-trade minute |
| Binance candle with irregular start or close timing | Source record exists, but cannot be safely aligned to an exact UTC minute; quarantined |
| Date before or after the supplied Binance history | Outside this archive's coverage, not evidence of zero trading |
| Kraken interval absent from its faithfully imported OHLCVT archive | Publisher-reported no-trade interval under Kraken's stated archive convention |
| Kraken API minute absent from the verified complete trade stream | No trades in that minute in the stored stream; no local collection omission found |

Kraken [explicitly documents](https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data)
that its historical OHLCVT archive contains only intervals with trades. The audit
reconciled **all 1,959,131 in-period archived XMR candles** to the normalized file,
including their timestamps and OHLCVT values, with **zero local omissions**. For
July 1 through October 2, 2026, all 94,255 minute buckets matched 761,308 unique
included trades across 763 preserved API pages; the cursor chain reached the
cutoff, with no missing included trade IDs.

Thus the evidence supports genuinely sparse Kraken XMR/USD trading for ordinary
absent minutes, rather than failures in our collection. This is exchange-specific:
Monero can trade on Binance in a minute when Kraken has no XMR/USD trade. Faithful
import establishes agreement with the publisher, not independent completeness of
every trade in Kraken's entire historical archive.

Trading halts are another cause of no trades. Kraken's
[January 11 upgrade announcement](https://blog.kraken.com/news/system-upgrade)
and [January 13 reopening notice](https://blog.kraken.com/news/kraken-returns-with-free-trading)
provide context for the prolonged January 2018 absence. The precise missing-candle
interval is not used to infer an independently verified downtime boundary.

All **76 supplied Binance monthly CSVs match the official downloaded ZIP payloads
exactly**, and all ZIPs pass Binance's official checksum files. Therefore their
source gaps and timing anomalies were not introduced by extraction or our import:

- 3,294,185 original candles, including **211,766 explicit zero-trade candles**.
- **7,544 absent source minute-start slots** between the archive's actual endpoints,
  counting the original timestamp's UTC-minute bucket before quarantining.
- **21,617 timing-anomalous rows** quarantined. Most are shifted starts in December
  2017 and February 2018; other anomalies include premature or invalid close times.
- 3,062,434 usable, correctly timed Binance minutes with positive trading.
- 168,515 of those minutes lack a same-minute Kraken BTC/USD trade, so they remain
  usable as native XMR/BTC observations but cannot create USD observations.

The CSV separately records valid zero-trade candles, absent source slots,
source-present but irregular slots, outside-archive slots and quarantined row
counts. Quarantined rows and minute slots differ where irregular source candles
share a UTC-minute bucket. The mutually exclusive slot counts reconcile to 60
per hour. In the validly timed subset, 210,134 zero-trade minutes remain.

## Currency conversion and source choice

For each minute with a fresh Kraken XMR/USD candle, preserve its close. Otherwise,
use a fresh, correctly timed Binance XMR/BTC close **only when Kraken BTC/USD has
a trade candle in the exact same UTC minute**:

`XMR/USD proxy = Binance XMR/BTC close × Kraken BTC/USD close`.

The hourly close is the last available minute close within that hour. Every close
retains its minute timestamp and source. All 35,371 hourly closes that use the
USD proxy are labelled. No BTC rate, XMR price, or zero-trade candle is carried
forward; no later minute is used to convert an earlier one.

The XMR/BTC series prefers a fresh native Binance price at each minute. Outside
those observations, it uses same-minute Kraken prices:

`XMR/BTC implied price = Kraken XMR/USD close ÷ Kraken BTC/USD close`.

USD and BTC-denominated hourly closes can select different last minutes because
their inputs differ. `xmr_btc_at_selected_usd_close` and
`btc_usd_at_selected_usd_close` provide the conversion at the selected USD close's
own minute. The independent `close_xmr_btc` has its own minute and source fields.

This dataset's main prices are **hourly closes**, not synthetic USD OHLC.
Multiplying the two markets' hourly highs or lows would combine extremes that
need not have occurred together. True native Binance XMR/BTC open, high, low,
close, base/quote volume and trade count are retained in separate `binance_*`
columns. Volume is not added across venues or represented as exact USD turnover.

Matching minute candles still does not mean simultaneous trade ticks. The USD
fallback is a cross-venue conversion proxy, not an observed Binance USD trade or
a guarantee of executable USD prices.

## How different are the prices?

Compare only minutes with positive Binance trading and both Kraken trade prices.
There are **1,006,922** such aligned minutes:

| Absolute difference from Kraken XMR/USD | Result |
| --- | ---: |
| Median | 0.1048% |
| 95th percentile | 0.5182% |
| 99th percentile | 1.5527% |
| Share exceeding 1% | 1.9300% |
| Share exceeding 5% | 0.1284% |

Typical prices are close enough to support a clearly labelled research proxy.
They are not interchangeable in every period. In the 2017 overlap, the median
absolute difference is 0.8370% and the 95th percentile is 4.4544%; February 2024
also has wider tails. At 2018-01-13 11:23 UTC, the retained Kraken close is $0.01
while the converted Binance close is about $405.21. That print is preserved and
flagged, not silently repaired or presumed to be a data-entry error. Kraken's
reopening notice says the markets resumed with empty order books and cautions
about illiquid-market orders.

**134 hours** contain at least one aligned-minute difference above the fixed 5%
diagnostic threshold. The CSV exposes the maximum difference, number of such
minutes, and `needs_price_review`. This flag does not delete records or certify
unflagged prices. At a filled minute, a simultaneous Kraken XMR price is absent,
so its actual contemporaneous venue difference cannot be measured.

There are 20,843 changes in the hourly USD close's selected source between
adjacent populated hours. Source switching can contribute to apparent returns.
Retain these fields in research and assess venue effects before replacing a
single-exchange training series. Denser observations improve freshness and
alignment; they do not imply 91.9% more independent training examples.

## Timing, precision and validation

Hours are UTC intervals `[timestamp_utc, available_after_utc)`. Use the complete
hour only after its ending timestamp. `close_age_seconds` measures hour end
minus the selected minute's start, an upper bound on its within-minute last-trade
age, not the exact last-trade timestamp. Empty prices stay blank; coverage counts
remain numerical. Numerical processing uses float64, exported with 17 significant
digits. The original decimal source files are preserved.

Validation independently recalculated all **84,399 USD** and **84,270 XMR/BTC**
hourly closes from their selected source minutes, and reconciled native Binance
OHLCVT for 54,542 hours. Coverage classes and denominators reconciled, original
Kraken hourly file hashes remained unchanged, and all **219 repository tests
passed** using the model environment plus bundled spreadsheet dependencies.
The Artifact Tool CSV export preserved every derived value and timestamp exactly,
and its representative data view was visually inspected.

Reproduction requires NumPy and pandas. The captured monthly ZIPs/checksums,
supplied archive, official verification ledger, comparison/coverage manifest,
collection audit and validation JSON are preserved alongside the dataset.

```sh
python scripts/verify_binance_xmr_archive.py data/raw/binance/Binance_XMRBTC_1m_2017-11_to_2024-02.zip
python scripts/build_combined_xmr_hourly.py
python scripts/audit_xmr_price_gaps.py
python -m unittest discover -s tests -p test_combined_xmr_hourly.py
```

Binance column definitions and checksum conventions:
[official public-data documentation](https://github.com/binance/binance-public-data).
