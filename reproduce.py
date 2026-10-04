"""One command that checks the headline numbers in docs/NOTE.md.

python reproduce.py

1. Python 3.12+ guard.
2. Unit tests (data build and model code).
3. Development retraining check (train_xmr_hourly_incident.py run --verify), only when the
   prepared features and raw minute files are present; otherwise reported as SKIPPED.
4. Pre-registered decision-rule bootstrap (scripts/preregistered_bootstrap.py) from saved predictions.
5. Note metrics and equity figure (scripts/note_metrics.py) from saved paper-policy ledgers.
6. Recompute the note's numbers from committed outputs and compare.

The out-of-sample period is never re-scored: its numbers are read from the committed outputs,
whose integrity is checked against the hashes recorded in oos_v1/results/RUN.json.
"""
import csv
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

if sys.version_info < (3, 12):
    sys.exit("Python 3.12+ is required (see README).")

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "hourly_models/docs/models/xmr_hourly_incident_catalog_v2"
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"[{'PASS' if ok is True else 'SKIP' if ok is None else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))


def run(cmd, cwd=ROOT):
    return subprocess.run([sys.executable, *cmd], cwd=cwd, capture_output=True, text=True)


def log_loss(rows, column):
    total = 0.0
    for r in rows:
        p = min(max(float(r[column]), 1e-15), 1 - 1e-15)
        total += -math.log(p) if r["target"] == "1" else -math.log(1 - p)
    return total / len(rows)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# 2. Unit tests
for label, folder in (("data-build tests", ROOT), ("model tests", ROOT / "hourly_models")):
    p = run(["-m", "unittest", "discover", "-s", "tests"], cwd=folder)
    check(label, p.returncode == 0, p.stderr.strip().splitlines()[-1] if p.stderr.strip() else "")

# 3. Development retraining check (needs non-committed inputs)
needed = [MODEL / "joined_features.csv", ROOT / "hourly_models/data/prices/xmr_usd_1m.csv.gz",
          ROOT / "hourly_models/data/prices/btc_usd_1m.csv.gz"]
if all(p.exists() for p in needed):
    p = run(["scripts/train_xmr_hourly_incident.py", "run", "--verify"], cwd=ROOT / "hourly_models")
    check("development retraining reproduces committed results", p.returncode == 0,
          (p.stdout + p.stderr).strip().splitlines()[-1] if (p.stdout + p.stderr).strip() else "")
else:
    check("development retraining", None, "needs prepared features and raw minute files (README: Rebuilding)")

# 4-5. Derived outputs from committed predictions and ledgers (no refitting)
for script in ("scripts/preregistered_bootstrap.py", "scripts/note_metrics.py"):
    p = run([script])
    check(script, p.returncode == 0, p.stderr.strip().splitlines()[-1] if p.returncode else "")

# 6. Compare with the numbers in docs/NOTE.md
dev = list(csv.DictReader(open(MODEL / "results/outer_predictions.csv")))
oos = list(csv.DictReader(open(MODEL / "oos_v1/results/predictions.csv")))
expected = [
    ("dev pooled log loss, market", round(log_loss(dev, "market_probability"), 4), 0.6377),
    ("dev pooled log loss, presence", round(log_loss(dev, "presence_probability"), 4), 0.6400),
    ("OOS log loss, presence", round(log_loss(oos, "presence_probability"), 5), 0.63486),
    ("OOS log loss, market", round(log_loss(oos, "market_probability"), 5), 0.63524),
]
boot_dev = json.loads((ROOT / "outputs/development/bootstrap_prereg.json").read_text())
boot_oos = json.loads((ROOT / "outputs/oos/bootstrap_prereg.json").read_text())
expected += [
    ("dev bootstrap mean (baseline - presence)", round(boot_dev["observed_mean_difference"], 5), -0.00224),
    ("dev bootstrap one-sided p", round(boot_dev["one_sided_p"], 3), 1.0),
    ("OOS bootstrap one-sided p", round(boot_oos["one_sided_p"], 3), 0.131),
]
dev_trades = sum(len(json.loads((MODEL / f"results/paper/fold_{k}_presence.json").read_text())["trades"]) for k in (1, 2, 3))
oos_trades = len(json.loads((MODEL / "oos_v1/results/paper/presence.json").read_text())["trades"])
expected += [("dev presence trades", dev_trades, 0), ("OOS presence trades", oos_trades, 1)]
for name, got, want in expected:
    check(name, got == want, f"got {got}, note says {want}")

# OOS integrity: committed outputs match the hashes written when the single run happened
run_log = json.loads((MODEL / "oos_v1/results/RUN.json").read_text())
bad = [f for f, h in run_log["output_sha256"].items() if sha256(MODEL / "oos_v1/results" / f) != h]
check("OOS outputs unchanged since the single run", not bad, ", ".join(bad))

failed = [n for n, ok in results if ok is False]
print("\nRESULT:", "FAIL" if failed else "PASS", f"({len(failed)} failed)" if failed else "")
sys.exit(1 if failed else 0)
