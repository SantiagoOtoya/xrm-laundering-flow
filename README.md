# XMR after large crypto thefts: an hourly forecast

Gator Quant Hacks 2026, Systematic Trading track.

**Hypothesis (pre-registered in [`HYPOTHESIS.md`](HYPOTHESIS.md)).** After a crypto theft with a known loss above $5M becomes public, attackers must convert stolen, traceable funds into a privacy coin before they are frozen. That forced, price-insensitive buying should push XMR/USD up over the following five days. We test whether knowing about a recent qualifying incident (whether one was reported in the last 24 hours, its known loss and its age) improves an hourly forecast of `P(five-day XMR return > h)` beyond what recent XMR and BTC returns and XMR volatility already say. The strategy buys XMR outright (no BTC hedge) when the forecast is at least 0.60, with costs of 200 bps per round trip.

**Result: not supported.** Adding the incident input made pooled development log loss worse (0.6400 vs 0.6377 for the market-only baseline; pre-registered bootstrap p = 1.0). Out-of-sample it was slightly better but not significant (0.63486 vs 0.63524; p = 0.131). The paper policy made 0 trades in development and 1 out-of-sample. Full write-up: [`docs/NOTE.pdf`](docs/NOTE.pdf).

## Results

Net of 200 bps round-trip costs. Development: outer tests 2020-11-26 to 2024-10-20. Out-of-sample: 2024-10-20 to 2026-10-03, scored once after the model and policy were frozen.

| Metric | Development (pooled) | Out-of-sample |
| --- | ---: | ---: |
| Eligible hours | 28,539 | 9,716 |
| Log loss, market baseline (features 1–5) | 0.6377 | 0.63524 |
| Log loss, presence model (features 1–6) | 0.6400 | 0.63486 |
| Mean (baseline − presence) log loss | −0.00224 | +0.00038 |
| Pre-registered one-sided p (168 h blocks, 10,000 draws, seed 20261004) | 1.0 | 0.131 |
| Paper policy trades (presence model) | 0 | 1 |
| Paper policy net return (2× costs) | 0.00% (0.00%) | +0.69% (+0.49%) |
| Buy-and-hold XMR | outer 1–3: +39.7%, −12.9%, −7.4% | +234.3% |

Hurdle `h` = 3% (predeclared fallback; no hurdle met the selection rules).

## Setup

Requires **Python 3.12+**.

```bash
git clone https://github.com/SantiagoOtoya/xrm-laundering-flow.git
cd xrm-laundering-flow
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Reproduce

```bash
python reproduce.py
```

Runs the unit tests, recomputes the pre-registered bootstrap and the note's metrics from the committed per-row predictions and trade ledgers, compares every headline number with `docs/NOTE.md`, and checks that the committed out-of-sample outputs still match the hashes recorded when they were produced. Prints PASS or FAIL. Takes about 10 seconds. It never re-scores the out-of-sample period.

## Rebuilding features from raw data (optional)

Retraining from scratch needs inputs that are not committed: the raw Kraken minute files (`data/prices/xmr_usd_1m.csv.gz`, `btc_usd_1m.csv.gz`) and the Binance archive (see [`data/README.md`](data/README.md) and the build scripts in `scripts/`). Place them under `hourly_models/data/prices/` and `hourly_models/data/raw/binance/`, put the hourly CSVs in `hourly_models/data/analysis/`, then run from `hourly_models/`:

```bash
python scripts/train_xmr_hourly_incident.py prepare
python scripts/train_xmr_hourly_incident.py run --verify
```

Use Python 3.12. `reproduce.py` runs the retraining check automatically when these inputs are present.

**Known issue:** regenerating `joined_features.csv` from the committed inputs currently gives different bytes from the file the committed results were trained on (the same on Python 3.12 and 3.14), so `run --verify` stops with "Training freeze manifest changed". The committed predictions and ledgers are the outputs of the original run.

## Repository map

| Path | Contents |
| --- | --- |
| `HYPOTHESIS.md` | Pre-registered hypothesis, specification and Amendment 1 |
| `reproduce.py` | The one command |
| `docs/NOTE.md`, `docs/NOTE.pdf` | Quant note |
| `hourly_models/` | Model code, tests, frozen specifications and all saved results (development and out-of-sample) |
| `scripts/` | Hourly price build, pre-registered bootstrap, note metrics |
| `data/` | Hourly price files, incident catalog instructions and checksums (no raw licensed data) |
| `outputs/` | Bootstrap and note metrics produced by `reproduce.py` |
| `tests/` | Data-build tests |

## Data sources

- **Prices:** Kraken spot XMR/USD and BTC/USD, hourly bars built from the Kraken OHLCVT trade-history archive.
- **Incidents:** DefiLlama hacks dataset, SlowMist Hacked, rekt.news leaderboard, and the primary sources they link.
- **Costs:** Kraken Pro fee schedule.

Full citations and licensing notes: [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md).

## Team

- Santiago Otoya
- Camilo Nunez

## Limitations

- Prices come from one exchange (Kraken) and are not a cross-exchange average.
- Costs are a constant 200 bps per round trip. This does not model size-dependent slippage or historical fee tiers.
- The incident catalog has day-level dates. The point-in-time availability times and known losses that features 6–8 need are reconstructed separately (see `HYPOTHESIS.md`, Disclosure).
- Hourly five-day labels overlap (neighbouring rows share 119 of 120 hours), so the row count overstates the number of independent observations.
- Capacity is not modelled; position size relative to XMR's hourly volume is reported as a limitation in the note.
