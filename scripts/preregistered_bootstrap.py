"""Pre-registered decision-rule bootstrap (HYPOTHESIS.md, Amendment 1), from saved predictions.

Statistic: mean over rows of (market per-row log loss - presence per-row log loss).
Circular block bootstrap over contiguous calendar hours, 168-hour blocks,
10,000 resamples, seed 20261004. One-sided p = share of resample means <= 0.
No model is refitted; only the saved per-row probabilities are read.
"""
import csv
import json
import math
import random
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "hourly_models/docs/models/xmr_hourly_incident_catalog_v2"
RUNS = {
    "development": MODEL / "results/outer_predictions.csv",
    "oos": MODEL / "oos_v1/results/predictions.csv",
}
BLOCK_HOURS, RESAMPLES, SEED = 168, 10_000, 20261004


def row_loss(y, p):
    p = min(max(p, 1e-15), 1 - 1e-15)
    return -math.log(p) if y == 1 else -math.log(1 - p)


def hour_index(ts):
    return int(datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").timestamp()) // 3600


def run(path):
    rows = list(csv.DictReader(open(path)))
    hours = [hour_index(r["decision_time"]) for r in rows]
    diffs = [row_loss(int(r["target"]), float(r["market_probability"]))
             - row_loss(int(r["target"]), float(r["presence_probability"])) for r in rows]
    start, n_hours = min(hours), max(hours) - min(hours) + 1
    sums, counts = [0.0] * n_hours, [0] * n_hours
    for h, d in zip(hours, diffs):
        sums[h - start] += d
        counts[h - start] += 1
    # Circular prefix sums so any 168-hour window (wrapping at the end) is O(1).
    ext_s, ext_c = sums + sums[:BLOCK_HOURS], counts + counts[:BLOCK_HOURS]
    ps, pc = [0.0], [0]
    for s, c in zip(ext_s, ext_c):
        ps.append(ps[-1] + s)
        pc.append(pc[-1] + c)
    block_s = [ps[i + BLOCK_HOURS] - ps[i] for i in range(n_hours)]
    block_c = [pc[i + BLOCK_HOURS] - pc[i] for i in range(n_hours)]
    n_blocks = math.ceil(n_hours / BLOCK_HOURS)
    rng = random.Random(SEED)
    means = []
    for _ in range(RESAMPLES):
        s = c = 0
        for _ in range(n_blocks):
            i = rng.randrange(n_hours)
            s += block_s[i]
            c += block_c[i]
        means.append(s / c)
    means.sort()
    observed = sum(diffs) / len(diffs)
    return dict(
        rows=len(rows), calendar_hours=n_hours, blocks_per_resample=n_blocks,
        statistic="mean(market per-row log loss - presence per-row log loss); positive favors presence",
        observed_mean_difference=observed,
        one_sided_p=sum(m <= 0 for m in means) / RESAMPLES,
        percentile_95=[means[int(0.025 * RESAMPLES)], means[int(0.975 * RESAMPLES) - 1]],
        block_hours=BLOCK_HOURS, resamples=RESAMPLES, seed=SEED,
        rng="Python random.Random (Mersenne Twister)",
        method="Circular block bootstrap over contiguous calendar hours; block starts uniform over the pooled span; "
               "hours without an eligible row contribute nothing; no refitting.",
        supported=(sum(m <= 0 for m in means) / RESAMPLES) < 0.05,
        source=str(path.relative_to(ROOT)),
    )


if __name__ == "__main__":
    for name, path in RUNS.items():
        out = ROOT / "outputs" / name / "bootstrap_prereg.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        result = run(path)
        out.write_text(json.dumps(result, indent=2) + "\n")
        print(name, json.dumps(result))
