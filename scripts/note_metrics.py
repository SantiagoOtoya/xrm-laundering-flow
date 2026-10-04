"""Derived note metrics and equity figure from saved paper-policy ledgers (no refitting).

Writes outputs/note_metrics.json and docs/figures/equity.svg.
Annualized return = (E_end/E_start)^(365/days) - 1; volatility = stdev of daily simple
returns x sqrt(365) (days with a missing mark are skipped); Sharpe = mean daily return x 365 / volatility,
zero risk-free rate. Turnover = sum over trades of (entry notional + exit notional), as a fraction of
equity, per year. Volume: Binance XMR/BTC hourly volume in XMR x combined USD close (Binance only).
"""
import csv
import json
import math
import statistics
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "hourly_models/docs/models/xmr_hourly_incident_catalog_v2"
SERIES = {
    **{f"dev_fold_{k}_{m}": MODEL / f"results/paper/fold_{k}_{f}.json"
       for k in (1, 2, 3) for m, f in (("presence", "presence"), ("presence_2x", "presence_double_cost"), ("buy_hold", "buy_hold"))},
    "oos_presence": MODEL / "oos_v1/results/paper/presence.json",
    "oos_presence_2x": MODEL / "oos_v1/results/paper/presence_double_cost.json",
    "oos_buy_hold": MODEL / "oos_v1/results/paper/buy_and_hold.json",
}


def day(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")


def stats(path):
    d = json.loads(path.read_text())
    eq = d["daily_equity"]
    days = (day(eq[-1]["timestamp"]) - day(eq[0]["timestamp"])).days
    rets = [b["equity"] / a["equity"] - 1 for a, b in zip(eq, eq[1:])
            if a["equity"] is not None and b["equity"] is not None]
    vol = statistics.pstdev(rets) * math.sqrt(365) if rets else 0.0
    total = eq[-1]["equity"] / eq[0]["equity"] - 1
    turnover = sum(t["initial_notional"] * (2 + t["gross_return"]) for t in d["trades"]) / (days / 365)
    return dict(days=days, net_return=total, annualized_return=(1 + total) ** (365 / days) - 1,
                annualized_volatility=vol,
                sharpe=(statistics.fmean(rets) * 365 / vol) if vol > 0 else None,
                max_drawdown=d["policy"]["maximum_drawdown"],
                max_drawdown_observed=d["policy"]["maximum_drawdown_observed"],
                completed_trades=len(d["trades"]), turnover_per_year=turnover, source=str(path.relative_to(ROOT)))


def binance_volume():
    rows = csv.DictReader(open(ROOT / "data/analysis/xmr_usd_btc_combined_1h.csv"))
    periods = {"outer_1": ("2020-11-26", "2022-03-15T16"), "outer_2": ("2022-03-15T16", "2023-07-03T08"),
               "outer_3_to_delisting": ("2023-07-03T08", "2024-02-20T03")}
    vols = {k: [] for k in periods}
    for r in rows:
        if not r["binance_volume_xmr"] or not r["close_usd"]:
            continue
        for k, (a, b) in periods.items():
            if a <= r["timestamp_utc"] < b:
                vols[k].append(float(r["binance_volume_xmr"]) * float(r["close_usd"]))
    return {k: dict(hours=len(v), median_usd=statistics.median(v)) for k, v in vols.items()}


def svg(curves):
    w, h, pad = 640, 210, 40
    panels = [("Development outer tests 1-3 (chained)", curves["dev"]), ("Out-of-sample", curves["oos"])]
    pw = (w - 3 * pad) / 2
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="sans-serif" font-size="10">']
    for i, (title, series) in enumerate(panels):
        x0 = pad + i * (pw + pad)
        vals = [v for s in series.values() for v in s if v is not None]
        lo, hi = math.log(min(vals)), math.log(max(vals))
        n = max(len(s) for s in series.values())
        out.append(f'<text x="{x0}" y="14" font-weight="bold">{title}</text>')
        out.append(f'<rect x="{x0}" y="22" width="{pw}" height="{h-62}" fill="none" stroke="#999"/>')
        for tick in (0.5, 1, 2, 3):
            if lo <= math.log(tick) <= hi:
                y = 22 + (h - 62) * (1 - (math.log(tick) - lo) / (hi - lo))
                out.append(f'<line x1="{x0}" x2="{x0+pw}" y1="{y:.1f}" y2="{y:.1f}" stroke="#ddd"/>'
                           f'<text x="{x0-4}" y="{y+3:.1f}" text-anchor="end">{tick}</text>')
        for (name, s), color in zip(series.items(), ("#1f4e9c", "#c0392b")):
            pts = " ".join(f"{x0 + pw * j / (n - 1):.1f},{22 + (h - 62) * (1 - (math.log(v) - lo) / (hi - lo)):.1f}"
                           for j, v in enumerate(s) if v is not None)
            out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.3"/>')
        out.append(f'<text x="{x0}" y="{h-26}">equity, log scale, start = 1</text>')
    out.append(f'<line x1="{pad}" x2="{pad+18}" y1="{h-10}" y2="{h-10}" stroke="#1f4e9c" stroke-width="2"/>'
               f'<text x="{pad+22}" y="{h-7}">Paper policy, presence model (10% per trade, 200 bps)</text>'
               f'<line x1="{pad+300}" x2="{pad+318}" y1="{h-10}" y2="{h-10}" stroke="#c0392b" stroke-width="2"/>'
               f'<text x="{pad+322}" y="{h-7}">Buy-and-hold XMR (100%, 200 bps)</text></svg>')
    return "\n".join(out)


def chained(paths):
    out, scale = [], 1.0
    for p in paths:
        eq = [e["equity"] for e in json.loads(p.read_text())["daily_equity"]]
        out += [None if v is None else v * scale for v in eq]
        scale *= eq[-1]
    return out


if __name__ == "__main__":
    result = {k: stats(p) for k, p in SERIES.items()}
    result["binance_hourly_volume_usd"] = binance_volume()
    (ROOT / "outputs").mkdir(exist_ok=True)
    (ROOT / "outputs/note_metrics.json").write_text(json.dumps(result, indent=2) + "\n")
    curves = {"dev": {"policy": chained([SERIES[f"dev_fold_{k}_presence"] for k in (1, 2, 3)]),
                      "bh": chained([SERIES[f"dev_fold_{k}_buy_hold"] for k in (1, 2, 3)])},
              "oos": {"policy": [e["equity"] for e in json.loads(SERIES["oos_presence"].read_text())["daily_equity"]],
                      "bh": [e["equity"] for e in json.loads(SERIES["oos_buy_hold"].read_text())["daily_equity"]]}}
    (ROOT / "docs/figures").mkdir(exist_ok=True)
    (ROOT / "docs/figures/equity.svg").write_text(svg(curves))
    print(json.dumps(result, indent=1))
