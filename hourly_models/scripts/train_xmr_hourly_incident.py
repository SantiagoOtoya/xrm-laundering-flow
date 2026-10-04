"""NEWMODELS.MD retrospective catalog-date experiment: prepare, freeze, run.

prepare freezes inputs/rules and writes outcome-free eligibility artifacts.
freeze checks catalog structure and binary-fit support. run requires that freeze.
This entry point never parses reserved price values or evaluates OOS outcomes.
"""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
import platform
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
# The amended run has a separate identity; earlier readiness and baseline
# artifacts remain intact. Catalog proxies never become verified live alerts.
DEFAULT_SPEC = {
    "study_id": "xmr_hourly_incident_catalog_v2",
    "incident_mode": "retrospective_catalog_date",
    "xmr_path": "data/analysis/xmr_usd_btc_combined_1h.csv",
    "btc_path": "data/analysis/btc_usd_1h.csv",
    "incident_directory": "data/curated/incident_information_v1",
    "incident_catalog_path": "data/curated/incidents_over_1m.csv",
    "expected_catalog_rows": 588,
    "baseline_selection_path": "docs/models/xmr_hourly_price_baseline_v1/SELECTED.json",
    "baseline_freeze_path": "docs/models/xmr_hourly_price_baseline_v1/FROZEN.json",
    "baseline_run_path": "docs/models/xmr_hourly_price_baseline_v1/results/RUN.json",
    "price_review_path": "docs/models/xmr_hourly_price_baseline_v1/PRICE_REVIEW.json",
    "history_start": "2017-01-02T00:00:00Z",
    "history_end_exclusive": "2026-10-03T00:00:00Z",
    "development_end_exclusive": "2024-10-20T00:00:00Z",
    "initial_development_end": "2020-11-26T00:00:00Z",
    "outer_ends": ["2022-03-15T16:00:00Z", "2023-07-03T08:00:00Z", "2024-10-20T00:00:00Z"],
    "horizon_hours": 120,
    "maximum_close_age_seconds": 300,
    "incident_threshold_usd": "5000000",
    "incident_active_hours": 24,
    "structural_incident_rule": "Fail before fitting for empty/duplicate IDs, malformed assigned dates, or nonfinite/nonpositive reported USD losses. Historical availability, amount-basis and identity-review uncertainties are disclosed rather than excluded.",
    "fixed_hurdle": 0.03,
    "fallback_hurdle": 0.03,
    "hurdle_selection_repeated": False,
    "l2_candidates": [0.01, 0.1, 1.0],
    "classification_threshold": 0.5,
    "paper_entry_probability": 0.6,
    "paper_notional_fraction": 0.1,
    "round_trip_cost": 0.02,
    "paper_fill_delay_hours": 1,
    "price_review_rule": "Reuse the completed baseline's frozen source-review dispositions on the unchanged snapshot at every feature, target, fill, exit and mark endpoint.",
    "incident_activation_convention": "00:00 UTC on the calendar day after the assigned incident_date; an assumed retrospective alignment, not verified public availability.",
    "incident_magnitude_convention": "Frozen catalog reported_loss_usd; retrospective reported amount, not verified gross theft or loss known at activation.",
    "catalog_absence_convention": "Zero means no qualifying entry in this frozen catalog's 24-hour window; unknown historical reporting coverage does not exclude ordinary hours.",
    "minimum_selection_trades": 10,
    "maximum_selection_drawdown": 0.1,
    "missing_portfolio_mark_rule": "Unknown intermediate marks make drawdown incomplete and the economic candidate ineligible.",
    "optimizer_max_iterations": 100,
    "optimizer_gradient_tolerance": 1e-8,
    "uncertainty_block_hours": 168,
    "bootstrap_replicates": 300,
    "random_seed": 17,
    "reserved_period_evaluation_allowed": False,
    "prior_holdout_inspection_disclosed": True,
    "baseline_outer_scores_inspected_before_amendment": True,
}
OUT = "docs/models/xmr_hourly_incident_catalog_v2"
HOUR = 3600
FEATURES = ["xmr_return_24h", "xmr_return_preceding_6d", "btc_return_24h",
            "btc_return_preceding_6d", "xmr_realized_volatility_24h",
            "incident_present_24h", "incident_catalog_loss_log", "incident_age_hours"]
MODELS = {"market": 5, "presence": 6, "full_incident": 8}
COMBINED_SOURCES = {
    "binance_archive": "data/raw/binance/Binance_XMRBTC_1m_2017-11_to_2024-02.zip",
    "price_coverage": "data/prices/price_coverage.json",
    "xmr_minute": "data/prices/xmr_usd_1m.csv.gz",
    "btc_minute": "data/prices/btc_usd_1m.csv.gz",
    "official_verification": "data/raw/binance/official_verification.json",
}
DISCLOSURE = "Reserved historical outcomes were inspected earlier in the project; this is not an untouched historical holdout. Stronger confirmation requires future observations after a full policy freeze."
AMENDMENT_DISCLOSURE = "The price-only outer development scores were inspected before this catalog-date amendment. These paired chronological results are exploratory retrospective evidence, not prospectively specified independent tests. Catalog dates and eventual losses can introduce look-ahead and reporting-selection bias; next-day activation does not eliminate either. No live incident-alert edge is established."


def iso(value):
    return dt.datetime.fromtimestamp(int(value), dt.timezone.utc).isoformat().replace("+00:00", "Z")


def timestamp(value):
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() != dt.timedelta(0) or parsed.minute or parsed.second or parsed.microsecond:
        raise ValueError("Expected an exact UTC hour")
    return int(parsed.timestamp())


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def csv_bytes(rows, fields):
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue().encode()


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def inner_bounds(start, end):
    hours = (end - start) // HOUR
    middle = start + hours // 2 * HOUR
    remainder = (end - middle) // HOUR
    bounds = [middle + remainder * i // 3 * HOUR for i in range(4)]
    return list(zip(bounds, bounds[1:]))


def validate_spec(spec):
    fixed = dict(horizon_hours=120, maximum_close_age_seconds=300,
        xmr_path="data/analysis/xmr_usd_btc_combined_1h.csv", btc_path="data/analysis/btc_usd_1h.csv",
        incident_threshold_usd="5000000", incident_active_hours=24,
        incident_mode="retrospective_catalog_date", fixed_hurdle=.03, fallback_hurdle=.03,
        hurdle_selection_repeated=False, l2_candidates=[.01, .1, 1.0],
        classification_threshold=.5, paper_entry_probability=.6,
        paper_notional_fraction=.1, round_trip_cost=.02, paper_fill_delay_hours=1,
        minimum_selection_trades=10, maximum_selection_drawdown=.1,
        reserved_period_evaluation_allowed=False, prior_holdout_inspection_disclosed=True,
        baseline_outer_scores_inspected_before_amendment=True)
    for key, value in fixed.items():
        if spec.get(key) != value:
            raise ValueError("NEWMODELS.MD fixed rule changed: " + key)
    if spec["uncertainty_block_hours"] < 120 or spec["bootstrap_replicates"] < 1:
        raise ValueError("Uncertainty requires blocks of at least 120 hours")
    start, end, cutoff = map(timestamp, [spec["history_start"], spec["history_end_exclusive"], spec["development_end_exclusive"]])
    days = (end - start) // (24 * HOUR)
    if days <= 0 or end - start != days * 24 * HOUR or cutoff != end - math.ceil(days / 5) * 24 * HOUR:
        raise ValueError("Reserve the latest 20% of calendar history rounded up to a UTC day")
    initial = timestamp(spec["initial_development_end"])
    if initial != start + (cutoff - start) // (2 * HOUR) * HOUR:
        raise ValueError("A must occupy half of development")
    expected = [initial + ((cutoff - initial) // HOUR) * i // 3 * HOUR for i in (1, 2, 3)]
    if list(map(timestamp, spec["outer_ends"])) != expected:
        raise ValueError("Three equal calendar outer blocks required")
    return start, cutoff


def read_closes(path, start, cutoff, maximum_age, audit=None, dispositions=None):
    """Filter raw bar-start time BEFORE parsing any reserved numeric value."""
    n = (cutoff - start) // HOUR
    prices = np.full(n + 1, np.nan)
    quality = ["missing_boundary_price"] * (n + 1)
    previous = None
    with Path(path).open(newline="") as handle:
        for row in csv.DictReader(handle):
            bar_start = int(row["timestamp_unix"])
            if bar_start >= cutoff:
                break
            if previous is not None and bar_start <= previous:
                raise ValueError("Prices require unique chronological timestamps")
            previous = bar_start
            if bar_start < start:
                continue
            if (bar_start - start) % HOUR or timestamp(row["timestamp_utc"]) != bar_start:
                raise ValueError("Inconsistent hourly source timestamp")
            i = (bar_start + HOUR - start) // HOUR
            flagged = row.get("needs_price_review") == "1"
            review = (dispositions or {}).get(bar_start)
            if flagged and dispositions is not None and review is None:
                raise ValueError("Flagged development price lacks the baseline's frozen disposition")
            disposition = review["disposition"] if review else "unresolved" if flagged else "unflagged"
            if audit is not None:
                audit.append(dict(bar_start=iso(bar_start), boundary_time=iso(bar_start + HOUR),
                    **{key: row.get(key, "") for key in ("close_usd_source", "close_usd_minute_utc", "close_age_seconds",
                        "close_uses_usd_proxy", "close_source_changed_from_prior_hour", "needs_price_review")},
                    price_review_disposition=disposition,
                    price_review_reason=review["reason"] if review else "Flagged price has no evidence-based acceptance; retain unresolved." if flagged else "",
                    reviewed_without_return_outcomes=True))
            if flagged and disposition != "accepted":
                quality[i] = disposition + "_price_review"
                continue
            if not row["close_usd"] or not row["close_age_seconds"]:
                continue
            try:
                price, age = float(row["close_usd"]), float(row["close_age_seconds"])
            except ValueError:
                quality[i] = "invalid_boundary_price_or_age"
                continue
            if not math.isfinite(price) or price <= 0 or not math.isfinite(age) or age < 60:
                quality[i] = "invalid_boundary_price_or_age"
            elif age > maximum_age:
                quality[i] = "stale_boundary_price"
            else:
                prices[i], quality[i] = price, "valid"
    return prices, quality


def catalog_windows(rows, spec):
    """Validate every catalog group and freeze its assigned next-day mapping."""
    ids, windows, audit = set(), defaultdict(list), []
    for row in rows:
        identity, assigned = row.get("incident_id", ""), row.get("incident_date", "")
        if not identity.strip() or identity in ids:
            raise ValueError("Catalog structural check: empty or duplicate incident_id")
        ids.add(identity)
        try:
            day = dt.date.fromisoformat(assigned)
            if day.isoformat() != assigned:
                raise ValueError("Noncanonical calendar date")
            amount = Decimal(row.get("reported_loss_usd", ""))
            if not amount.is_finite() or amount <= 0 or not math.isfinite(float(amount)):
                raise ValueError("Nonfinite/nonpositive amount")
        except (ValueError, ArithmeticError) as error:
            raise ValueError("Catalog structural check failed for " + identity + ": " + str(error)) from error
        activation = int(dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), dt.timezone.utc).timestamp())
        qualifies = amount > Decimal(spec["incident_threshold_usd"])
        record = dict(row, assumed_activation_utc=iso(activation),
            qualifies_over_5m=qualifies, timing_assumption=spec["incident_activation_convention"],
            magnitude_assumption=spec["incident_magnitude_convention"],
            verified_information_available_at_activation=False)
        audit.append(record)
        if qualifies:
            event = dict(incident_id=identity, incident_date=assigned, loss=amount, activation=activation)
            for age in range(spec["incident_active_hours"]):
                windows[activation + age * HOUR].append(event)
    return dict(windows), audit


def incident_features(decision, windows, spec):
    """Catalog presence, fixed retrospective magnitude and assumed-clock age."""
    active = windows.get(decision, [])
    audit = dict(reason="", selected_incident_id="", assumed_activation_utc="", assigned_incident_date="",
        selected_catalog_loss_usd="", incident_timing_mode="retrospective_catalog_next_day",
        active_incident_ids=sorted(row["incident_id"] for row in active),
        missing_required_sources=[], unresolved_incident_ids=[],
        coverage_status="assumed_frozen_catalog_population", verified_information_available=False)
    if not active:
        return [0., 0., 0.], audit
    selected = min(active, key=lambda row: (-row["loss"], row["activation"], row["incident_id"]))
    audit.update(selected_incident_id=selected["incident_id"], assumed_activation_utc=iso(selected["activation"]),
        assigned_incident_date=selected["incident_date"], selected_catalog_loss_usd=str(selected["loss"]))
    return [1., math.log1p(float(selected["loss"]) / 1e6), (decision-selected["activation"]) / HOUR], audit


@dataclass
class Frame:
    start: int
    cutoff: int
    xmr: np.ndarray
    btc: np.ndarray
    x: np.ndarray
    outcome_eligible: np.ndarray
    future_return: np.ndarray
    audit: list
    exclusions: list
    price_audit: list = None
    catalog_audit: list = None

    @property
    def times(self):
        return self.start + np.arange(len(self.x), dtype=np.int64) * HOUR

    @property
    def eligible(self):
        return np.isfinite(self.x).all(axis=1)


def build_frame(xmr, btc, start, cutoff, windows, spec, outcomes=False, quality=None):
    n = (cutoff - start) // HOUR
    if len(xmr) != n + 1 or len(btc) != n + 1:
        raise ValueError("XMR and BTC require one shared calendar grid")
    x, returns = np.full((n, 8), np.nan), np.full(n, np.nan)
    outcome_eligible, audits, exclusions = np.zeros(n, dtype=bool), [], []
    for i in range(n):
        decision = start + i * HOUR
        reasons = []
        if i < 168:
            reasons.append("incomplete_7day_feature_history")
        else:
            xmr_endpoints = np.r_[i - 168, np.arange(i - 24, i + 1)]
            btc_endpoints = np.array([i, i - 24, i - 168])
            for asset, prices, endpoints in (("xmr", xmr, xmr_endpoints), ("btc", btc, btc_endpoints)):
                invalid = endpoints[~np.isfinite(prices[endpoints]) | (prices[endpoints] <= 0)]
                if len(invalid):
                    reasons.append("missing_or_stale_" + asset + "_feature_price")
                    if quality is not None:
                        reasons.extend(asset + "_feature_" + r for r in sorted({quality[asset][j] for j in invalid}))
            if not reasons:
                x[i, :5] = [math.log(xmr[i] / xmr[i - 24]), math.log(xmr[i - 24] / xmr[i - 168]),
                    math.log(btc[i] / btc[i - 24]), math.log(btc[i - 24] / btc[i - 168]),
                    float(np.sqrt(np.square(np.diff(np.log(xmr[i - 24:i + 1]))).sum()))]
        values, audit = incident_features(decision, windows, spec)
        x[i, 5:] = values
        reasons.extend(filter(None, audit["reason"].split(";")))
        audits.append(audit)
        target_i = i + spec["horizon_hours"]
        if target_i > n:
            reasons.append("target_crosses_development_boundary")
        elif not np.isfinite(xmr[i]) or xmr[i] <= 0 or not np.isfinite(xmr[target_i]) or xmr[target_i] <= 0:
            reasons.append("missing_or_stale_target_endpoint")
            if quality is not None:
                reasons.extend("xmr_target_" + r for r in sorted({quality["xmr"][j] for j in (i, target_i) if quality["xmr"][j] != "valid"}))
        else:
            outcome_eligible[i] = True
            if outcomes and np.isfinite(x[i]).all():
                returns[i] = xmr[target_i] / xmr[i] - 1
        for reason in dict.fromkeys(reasons):
            exclusions.append(dict(decision_time=iso(decision), reason=reason,
                selected_incident_id=audit["selected_incident_id"],
                unresolved_incident_ids=json.dumps(audit["unresolved_incident_ids"]),
                missing_required_sources=json.dumps(audit["missing_required_sources"])))
    return Frame(start, cutoff, xmr, btc, x, outcome_eligible, returns, audits, exclusions)


def load_frame(spec, root=ROOT, outcomes=False):
    start, cutoff = validate_spec(spec)
    price_audit = []
    ledger = json.loads((root / spec["price_review_path"]).read_text())
    if ledger["xmr_source_sha256"] != digest(root / spec["xmr_path"]) or ledger["development_end_exclusive"] != spec["development_end_exclusive"]:
        raise ValueError("Baseline price review does not describe the unchanged development snapshot")
    dispositions = {timestamp(row["bar_start"]): row for row in ledger["rows"]}
    if len(dispositions) != len(ledger["rows"]) or any(row["disposition"] not in ("accepted", "invalid", "unresolved") or not row["reason"] for row in dispositions.values()):
        raise ValueError("Malformed frozen price-review dispositions")
    xmr, qx = read_closes(root / spec["xmr_path"], start, cutoff, spec["maximum_close_age_seconds"], audit=price_audit, dispositions=dispositions)
    btc, qb = read_closes(root / spec["btc_path"], start, cutoff, spec["maximum_close_age_seconds"])
    if set(dispositions) != {timestamp(row["bar_start"]) for row in price_audit if row["needs_price_review"] == "1"}:
        raise ValueError("Frozen price-review membership changed")
    with (root / spec["incident_catalog_path"]).open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != spec["expected_catalog_rows"]:
        raise ValueError("Catalog row count changed from the amended 588-row snapshot")
    windows, catalog_audit = catalog_windows(rows, spec)
    frame = build_frame(xmr, btc, start, cutoff, windows, spec, outcomes,
                        quality={"xmr": qx, "btc": qb})
    frame.price_audit = price_audit
    frame.catalog_audit = catalog_audit
    return frame


def sample_indices(frame, begin, end):
    t = frame.times
    return np.flatnonzero((t >= begin) & (t < end) & (t + 120 * HOUR <= end)
                         & frame.eligible & frame.outcome_eligible)


def readiness(frame, spec):
    initial = timestamp(spec["initial_development_end"])
    folds = [dict(training_end=iso(begin), validation_end=iso(end),
        training_rows=len(sample_indices(frame, frame.start, begin)),
        validation_rows=len(sample_indices(frame, begin, end))) for begin, end in inner_bounds(frame.start, initial)]
    ready = all(f["training_rows"] > 0 and f["validation_rows"] > 0 for f in folds)
    price_audit = frame.price_audit or []
    return dict(status="ready_for_pre_fit_freeze" if ready else "blocked_by_data_readiness",
        initial_selection_ready=ready, initial_selection_folds=folds,
        calendar_development_hours=len(frame.x), incident_eligible_hours=int(np.isfinite(frame.x[:, 5:]).all(axis=1).sum()),
        common_feature_eligible_hours=int(frame.eligible.sum()),
        common_label_eligible_hours=len(sample_indices(frame, frame.start, frame.cutoff)),
        unresolved_price_review_hours=sum(r["price_review_disposition"] == "unresolved" for r in price_audit),
        development_proxy_closes=sum(r["close_uses_usd_proxy"] == "1" for r in price_audit),
        development_source_switches=sum(r["close_source_changed_from_prior_hour"] == "1" for r in price_audit),
        exclusion_counts=dict(Counter(row["reason"] for row in frame.exclusions)),
        reserved_calendar_hours=(timestamp(spec["history_end_exclusive"]) - frame.cutoff) // HOUR,
        reserved_start=iso(frame.cutoff), reserved_numeric_prices_parsed=False,
        outcomes_calculated=bool(np.isfinite(frame.future_return).any()), prior_inspection_disclosure=DISCLOSURE,
        amendment_timing_disclosure=AMENDMENT_DISCLOSURE, incident_mode=spec["incident_mode"],
        catalog_structural_rows=len(frame.catalog_audit or []),
        qualifying_catalog_groups=sum(row["qualifies_over_5m"] for row in frame.catalog_audit or []),
        explanation="Catalog fields must be structurally valid; historical reporting availability/coverage do not gate this retrospective mode. The inherited 3% fallback remains fixed. Every fit must have both target classes; calendar boundaries and price eligibility are unchanged.")


def verify_price_snapshots(spec, root):
    reports = {}
    for asset in ("xmr", "btc"):
        path = root / spec[asset + "_path"]
        manifest = json.loads(path.with_suffix(".coverage.json").read_text())
        if (manifest["requested_start_utc"] != spec["history_start"] or
                manifest["requested_end_exclusive_utc"] != spec["history_end_exclusive"] or manifest["forward_filled"]):
            raise ValueError("Hourly snapshot boundaries or aggregation changed: " + asset)
        if digest(path) != manifest["sha256_csv"]:
            raise ValueError("Hourly/source snapshot hash mismatch: " + asset)
        builder = "scripts/build_combined_xmr_hourly.py" if asset == "xmr" else "scripts/build_hourly_prices.py"
        if digest(root / builder) != manifest["builder_sha256"]:
            raise ValueError("Hourly builder changed: rebuild and verify the snapshot")
        if asset == "xmr":
            if manifest["version"] != "xmr_combined_hourly_v1" or set(manifest["input_sha256"]) != set(COMBINED_SOURCES):
                raise ValueError("Combined XMR source schema changed")
            for key, source in COMBINED_SOURCES.items():
                if digest(root / source) != manifest["input_sha256"][key]:
                    raise ValueError("Combined XMR input hash mismatch: " + source)
            validation = json.loads((root / "docs/xmr_combined_hourly_validation.json").read_text())
            if validation["csv_sha256"] != manifest["sha256_csv"] or not validation["coverage_classes_reconciled"]:
                raise ValueError("Combined hourly independent validation mismatch")
            reports[asset] = {k: manifest[k] for k in ("sha256_csv", "input_sha256", "calendar_hours", "combined_observed_hours", "combined_empty_hours", "source_policy_usd", "numeric_policy")}
        else:
            if manifest["bar_seconds"] != HOUR or digest(root / manifest["source_path"]) != manifest["source_sha256_csv_gz"]:
                raise ValueError("BTC minute/hourly source mismatch")
            reports[asset] = {k: manifest[k] for k in ("sha256_csv", "source_sha256_csv_gz", "calendar_hours", "observed_hours", "empty_hours")}
    return reports


def inherited_selection(spec, root=ROOT):
    """Reference the saved baseline fallback; never rerun hurdle selection."""
    selected_path = root / spec["baseline_selection_path"]
    selected = json.loads(selected_path.read_text())
    archived_run = json.loads((root / spec["baseline_run_path"]).read_text())
    archived_freeze = json.loads((root / spec["baseline_freeze_path"]).read_text())
    if digest(selected_path) != archived_run["selected_sha256"] or digest(root / spec["baseline_freeze_path"]) != archived_run["freeze_sha256"]:
        raise ValueError("Archived baseline selection/freeze integrity mismatch")
    selection = selected["selection"]
    if selection["selected_hurdle"] != .03 or selection["fallback_used"] is not True or selection["economically_supported_hurdle"] is not False:
        raise ValueError("Amendment requires the already frozen 3% descriptive fallback")
    keys = ["xmr_path", "btc_path", "history_start", "history_end_exclusive", "development_end_exclusive",
        "initial_development_end", "outer_ends", "horizon_hours", "maximum_close_age_seconds", "l2_candidates",
        "classification_threshold", "paper_entry_probability", "paper_notional_fraction", "round_trip_cost", "paper_fill_delay_hours"]
    if selected["feature_names"] != FEATURES[:5] or any(selected["policy"][key] != spec[key] for key in keys):
        raise ValueError("Amended price/target/policy settings differ from the baseline freeze")
    for path in (spec["xmr_path"], spec["btc_path"], spec["price_review_path"]):
        if digest(root / path) != archived_freeze["input_sha256"][path]:
            raise ValueError("Baseline snapshot/review changed: " + path)
    return dict(selected_hurdle=.03, fallback_used=True, economically_supported_hurdle=False,
        selection_end=selection["selection_end"], selection_repeated=False,
        inherited_from=spec["baseline_selection_path"], inherited_sha256=digest(selected_path),
        baseline_original_specification_sha256=archived_freeze["input_sha256"]["NEWMODELS.MD"],
        warning="Inherited descriptive fallback, not an optimum or a tradable edge. " + AMENDMENT_DISCLOSURE)


def paired_cohort_check(frame, spec, root=ROOT):
    """Check archived calendar membership; all new comparisons are refitted."""
    run_path = root / spec["baseline_run_path"]
    manifest = json.loads(run_path.read_text())
    prediction_path = run_path.parent / "outer_predictions.csv"
    if digest(prediction_path) != manifest["output_sha256"]["outer_predictions.csv"]:
        raise ValueError("Archived baseline predictions changed")
    old = defaultdict(set)
    with prediction_path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            key, t = int(row["fold"]), timestamp(row["decision_time"])
            if t in old[key]:
                raise ValueError("Duplicate archived baseline decision")
            old[key].add(t)
    begin, reports = timestamp(spec["initial_development_end"]), []
    for number, end in enumerate(map(timestamp, spec["outer_ends"]), 1):
        training = sample_indices(frame, frame.start, begin)
        testing = sample_indices(frame, begin, end)
        times = set(map(int, frame.times[testing]))
        model_path = run_path.parent / f"models/fold_{number}.json"
        if digest(model_path) != manifest["output_sha256"][f"models/fold_{number}.json"]:
            raise ValueError("Archived baseline model changed")
        archived = json.loads(model_path.read_text())
        reports.append(dict(fold=number, new_training_rows=len(training), new_test_rows=len(testing),
            archived_training_rows=archived["training_rows"], archived_test_rows=len(old[number]),
            training_counts_match=len(training) == archived["training_rows"],
            exact_test_timestamp_membership_matches=times == old[number],
            training_cutoff_matches=archived["training_end_exclusive"] == iso(begin)))
        begin = end
    return dict(comparators_refitted=True, saved_predictions_reused=False,
        within_run_training_test_rows_identical_for_all_comparisons=True,
        archived_baseline_membership_checks=reports,
        note="Refitting on the common frame avoids assuming archived training-population identity from counts alone.")


def provenance_paths(spec, root=ROOT):
    paths = {"NEWMODELS.MD", "scripts/train_xmr_hourly_incident.py", "tests/test_xmr_hourly_incident.py", "requirements-analysis.txt",
        "scripts/build_hourly_prices.py", "scripts/build_combined_xmr_hourly.py", "scripts/verify_binance_xmr_archive.py",
        "docs/xmr_combined_hourly_validation.json", spec["incident_catalog_path"], spec["xmr_path"], spec["btc_path"],
        *COMBINED_SOURCES.values(), spec["baseline_selection_path"], spec["baseline_freeze_path"],
        spec["baseline_run_path"], spec["price_review_path"], "docs/dedup/baseline_crosswalk.csv"}
    baseline_folder = (root / spec["baseline_run_path"]).parent
    paths.add((baseline_folder / "outer_predictions.csv").relative_to(root).as_posix())
    paths.update((baseline_folder / f"models/fold_{number}.json").relative_to(root).as_posix() for number in (1, 2, 3))
    folder = root / spec["incident_directory"]
    for path in sorted(folder.iterdir()):
        if path.is_file():
            paths.add(path.relative_to(root).as_posix())
    # The information ledger is hashed as audit context. Its absent historical
    # receipt/coverage/loss evidence has no eligibility role in catalog mode.
    for asset in ("xmr", "btc"):
        path = root / spec[asset + "_path"]
        coverage = path.with_suffix(".coverage.json")
        paths.add(coverage.relative_to(root).as_posix())
        if asset == "btc":
            paths.add(json.loads(coverage.read_text())["source_path"])
    return sorted(paths)


def verify_inputs(spec, root=ROOT):
    lock = json.loads((root / OUT / "PRE_RUN.json").read_text())
    if lock["config"] != spec:
        raise ValueError("Rules/source boundaries changed after pre-run freeze; a replacement experiment is required")
    for path, expected in lock["input_sha256"].items():
        if digest(root / path) != expected:
            raise ValueError("Frozen input changed: " + path)
    return lock


def prepare(spec, root=ROOT, verify_only=False):
    validate_spec(spec)
    folder = root / OUT
    lock_path = folder / "PRE_RUN.json"
    if lock_path.exists():
        verify_inputs(spec, root)
    elif verify_only:
        raise ValueError("Missing pre-run manifest")
    else:
        prices = verify_price_snapshots(spec, root)
        selection = inherited_selection(spec, root)
        paths = provenance_paths(spec, root)
        lock = dict(study_id=spec["study_id"], frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
            config=spec, features=FEATURES, comparisons={"prevalence": [], **{name: FEATURES[:n] for name, n in MODELS.items()}},
            price_snapshot_verification=prices, input_sha256={path: digest(root / path) for path in paths},
            prior_inspection_disclosure=DISCLOSURE, amended_model_outcomes_inspected=False,
            amendment_timing_disclosure=AMENDMENT_DISCLOSURE, inherited_hurdle_selection=selection,
            reserved_period_evaluation_allowed=False, deviations_from_newmodels=[],
            implementation_choices=["Reuse the completed baseline's frozen 3% fallback; do not repeat or expand hurdle selection.",
                "Use assigned catalog dates with next-day UTC activation and frozen retrospective reported USD amounts; ordinary hours mean absence from this catalog window.",
                "Refit all three feature comparisons on the same price-eligible population with independent prescribed inner-L2 selection; preserve existing baseline files.",
                "168-hour paired calendar-block bootstrap, 300 draws, fixed seed 17.",
                "Missing intermediate portfolio prices leave drawdown unknown and economic selection ineligible.",
                "Combined XMR source metadata and the baseline's frozen price-review dispositions are retained unchanged.",
                "Paper fills use the next completed close, one hour after the signal, with a 120-hour hold from fill.",
                "Completed-close boundary proxies assumed available at their hour end; no historical feed-receipt latency is established."])
        prior = root / (OUT + "_superseded_original_source_preflight") / "PRE_RUN.json"
        if prior.exists():
            lock["superseded_preflight"] = dict(path=prior.relative_to(root).as_posix(), sha256=digest(prior),
                reason="Preliminary outcome-free original-source audit superseded by the explicit NEWMODELS.MD addition; no model fit, selection, or outcome score occurred.")
        folder.mkdir(parents=True, exist_ok=True)
        lock_path.write_bytes(json_bytes(lock))
    frame = load_frame(spec, root, outcomes=False)
    report = readiness(frame, spec)
    evidence = json.loads((root / spec["incident_directory"] / "summary.json").read_text())
    report["information_ledger_audit_context_only"] = {k: evidence[k] for k in ("catalog_incident_groups", "historical_availability_verified", "original_loss_known_at_detection_verified", "hourly_ready_incidents")}
    rows = []
    for i, t in enumerate(frame.times):
        row = dict(decision_time=iso(t), target_end=iso(t + 120 * HOUR), stage=stage_at(t, spec),
            feature_eligible=bool(frame.eligible[i]), target_price_eligible=bool(frame.outcome_eligible[i]))
        row.update({name: float(v) if np.isfinite(v) else "" for name, v in zip(FEATURES, frame.x[i])})
        audit = frame.audit[i]
        row.update({key: json.dumps(value) if isinstance(value, list) else value for key, value in audit.items()})
        rows.append(row)
    boundary_rows = boundary_exclusions(frame, spec)
    outputs = {"READINESS.json": json_bytes(report),
        "PAIRED_COHORT_CHECK.json": json_bytes(paired_cohort_check(frame, spec, root)),
        "joined_features.csv": csv_bytes(rows, list(rows[0])),
        "exclusions.csv": csv_bytes(frame.exclusions, ["decision_time", "reason", "selected_incident_id", "unresolved_incident_ids", "missing_required_sources"]),
        "boundary_exclusions.csv": csv_bytes(boundary_rows, ["context", "decision_time", "target_end", "boundary", "reason"]),
        "price_review.csv": csv_bytes(frame.price_audit, list(frame.price_audit[0])),
        "catalog_mapping.csv": csv_bytes(frame.catalog_audit, list(frame.catalog_audit[0])),
        "reserved_exclusion.json": json_bytes(dict(start=spec["development_end_exclusive"], end_exclusive=spec["history_end_exclusive"],
            calendar_hours=report["reserved_calendar_hours"], reason="reserved_OOS", numeric_values_parsed=False)),
        "READINESS.md": ("# Retrospective catalog-date model readiness\n\n" + DISCLOSURE + "\n\n" + AMENDMENT_DISCLOSURE + "\n\n" +
            f"Status: **{report['status']}**. Common eligible labeled development rows: {report['common_label_eligible_hours']}.\n\n" +
            "Current source snapshots and rules are recorded in PRE_RUN.json. The joined frame contains predictors and eligibility only; no future return or target label has been calculated.\n\n" +
            "Assigned catalog days activate at next-day 00:00 UTC; fixed retrospective reported loss must exceed $5m. Historical availability and reporting coverage are audit limitations, not readiness gates. The baseline's saved 3% fallback and price-review rules are retained. All fits require both classes, and all calendar purges remain fixed.\n").encode()}
    verify_inputs(spec, root)
    for path, data in outputs.items():
        dest = folder / path
        if verify_only:
            if dest.read_bytes() != data:
                raise ValueError("Preparation reproduction mismatch: " + path)
        elif dest.exists() and dest.read_bytes() != data:
            raise ValueError("Refusing to overwrite different preparation: " + path)
        elif not dest.exists():
            dest.write_bytes(data)
    manifest = dict(pre_run_sha256=digest(lock_path), model_fitted=False, outcomes_calculated=False,
        output_sha256={p: hashlib.sha256(data).hexdigest() for p, data in outputs.items()})
    dest = folder / "PREPARATION.json"
    if verify_only:
        if json.loads(dest.read_text()) != manifest:
            raise ValueError("Preparation manifest mismatch")
    else:
        dest.write_bytes(json_bytes(manifest))
    return report


def stage_at(t, spec):
    if t < timestamp(spec["initial_development_end"]):
        return "initial_A"
    for number, end in enumerate(spec["outer_ends"], 1):
        if t < timestamp(end):
            return "outer_" + str(number)
    return "reserved_OOS"


def boundary_exclusions(frame, spec):
    contexts = []
    initial = timestamp(spec["initial_development_end"])
    for number, (begin, end) in enumerate(inner_bounds(frame.start, initial), 1):
        contexts.extend([(f"selection_{number}_training", begin), (f"selection_{number}_validation", end)])
    for number, begin in enumerate([initial] + list(map(timestamp, spec["outer_ends"])), 1):
        contexts.append((f"outer_or_final_{number}_training", begin))
        for fold, (left, right) in enumerate(inner_bounds(frame.start, begin), 1):
            contexts.extend([(f"outer_or_final_{number}_inner_{fold}_training", left), (f"outer_or_final_{number}_inner_{fold}_validation", right)])
    contexts.extend((f"outer_{n}_test", timestamp(end)) for n, end in enumerate(spec["outer_ends"], 1))
    return [dict(context=context, decision_time=iso(t), target_end=iso(t + 120 * HOUR), boundary=iso(boundary),
                 reason="120hour_target_crosses_boundary") for context, boundary in contexts
            for t in frame.times[(frame.times < boundary) & (frame.times + 120 * HOUR > boundary)]]


def freeze(spec, root=ROOT):
    report = prepare(spec, root, verify_only=(root / OUT / "PRE_RUN.json").exists())
    if not report["initial_selection_ready"]:
        raise ValueError("Retrospective catalog/price readiness failed in fixed A folds; see READINESS.json")
    path = root / OUT / "FROZEN.json"
    data = json_bytes(dict(pre_run_sha256=digest(root / OUT / "PRE_RUN.json"),
        preparation_sha256=digest(root / OUT / "PREPARATION.json"), initial_selection_ready=True,
        prior_inspection_disclosure=DISCLOSURE))
    if path.exists() and path.read_bytes() != data:
        raise ValueError("Existing training freeze differs")
    path.write_bytes(data)


def verify_training_freeze(spec, root):
    verify_inputs(spec, root)
    folder = root / OUT
    if not (folder / "FROZEN.json").exists():
        raise ValueError("Missing readiness-approved FROZEN.json; prepare and freeze before fitting")
    freeze_record = json.loads((folder / "FROZEN.json").read_text())
    for name, key in (("PRE_RUN.json", "pre_run_sha256"), ("PREPARATION.json", "preparation_sha256")):
        if digest(folder / name) != freeze_record[key]:
            raise ValueError("Training freeze manifest changed")
    preparation = json.loads((folder / "PREPARATION.json").read_text())
    for name, expected in preparation["output_sha256"].items():
        if digest(folder / name) != expected:
            raise ValueError("Preparation artifact changed: " + name)


def sigmoid(z):
    return np.exp(-np.logaddexp(0.0, -z))


def fit(frame, indices, hurdle, penalty, end, spec, model_name="full_incident"):
    if (not len(indices) or np.any(frame.times[indices] >= end)
            or np.any(frame.times[indices] + 120 * HOUR > end)):
        raise ValueError("Empty training sample or target crossing training cutoff")
    raw = frame.x[indices, :MODELS[model_name]]
    if not frame.eligible[indices].all() or not np.isfinite(frame.future_return[indices]).all():
        raise ValueError("Training rows must pass common incident and price eligibility")
    y = (frame.future_return[indices] > hurdle).astype(float)
    if len(np.unique(y)) != 2:
        raise ValueError("Training requires both target classes")
    mean, scale = raw.mean(axis=0), raw.std(axis=0)
    constant = np.all(raw == raw[0], axis=0)
    scale = np.where(constant, 1.0, scale)
    a = np.column_stack((np.ones(len(indices)), (raw - mean) / scale))
    theta = np.zeros(a.shape[1])
    theta[0] = math.log(y.mean() / (1 - y.mean()))
    regularizer = np.diag([0.0] + [penalty] * raw.shape[1])

    def loss(v):
        logits = a @ v
        return float(np.mean(np.logaddexp(0, logits) - y * logits) + .5 * penalty * np.square(v[1:]).sum())

    for iteration in range(spec["optimizer_max_iterations"]):
        p = sigmoid(a @ theta)
        gradient = a.T @ (p - y) / len(y) + regularizer @ theta
        if np.abs(gradient).max() <= spec["optimizer_gradient_tolerance"]:
            break
        hessian = a.T @ (a * (p * (1 - p))[:, None]) / len(y) + regularizer
        direction = np.linalg.solve(hessian, gradient)
        old_loss, step = loss(theta), 1.0
        while step >= 2 ** -30:
            proposal = theta - step * direction
            if loss(proposal) <= old_loss - 1e-4 * step * float(gradient @ direction):
                theta = proposal
                break
            step *= .5
        else:
            raise ValueError("Optimizer line search failed")
    gradient = a.T @ (sigmoid(a @ theta) - y) / len(y) + regularizer @ theta
    if np.abs(gradient).max() > spec["optimizer_gradient_tolerance"]:
        raise ValueError("Optimizer failed numerical convergence")
    names = FEATURES[:raw.shape[1]]
    return dict(model_name=model_name, feature_names=names, scaler_mean=mean.tolist(), scaler_scale=scale.tolist(),
        constant_training_features=[name for name, flag in zip(names, constant) if flag],
        coefficients=theta[1:].tolist(), intercept=float(theta[0]), hurdle=hurdle, l2_lambda=penalty,
        training_rows=len(indices), training_prevalence=float(y.mean()), training_end_exclusive=iso(end),
        incident_mode=spec["incident_mode"], incident_predictors_are_retrospective=True,
        objective="mean BCE + lambda/2 * sum(beta squared); unpenalized intercept; natural hourly prevalence",
        convergence=dict(iterations=iteration + 1, gradient_linf=float(np.abs(gradient).max()), objective=loss(theta)))


def predict(model, x):
    raw = x[:, :len(model["feature_names"])]
    return sigmoid((raw - np.asarray(model["scaler_mean"])) / np.asarray(model["scaler_scale"])
                   @ np.asarray(model["coefficients"]) + model["intercept"])


def metrics(y, p):
    if not len(y):
        return dict(available=False, rows=0, positive_rows=0, negative_rows=0, auc=None)
    y, p = np.asarray(y), np.asarray(p)
    if not np.isfinite(p).all() or np.any((p < 0) | (p > 1)):
        raise ValueError("Invalid probabilities")
    clipped = np.clip(p, 1e-15, 1 - 1e-15)
    positives, auc = int(y.sum()), None
    if 0 < positives < len(y):
        order = np.argsort(p, kind="stable")
        lo = np.r_[0, np.flatnonzero(np.diff(p[order])) + 1]
        hi, ranks = np.r_[lo[1:], len(y)], np.empty(len(y))
        for first, last in zip(lo, hi):
            ranks[order[first:last]] = (first + 1 + last) / 2
        auc = float((ranks[y == 1].sum() - positives * (positives + 1) / 2) / (positives * (len(y) - positives)))
    bins = []
    for i in range(10):
        mask = (p >= i / 10) & ((p < (i + 1) / 10) if i < 9 else (p <= 1))
        if mask.any():
            bins.append(dict(lower=i / 10, upper=(i + 1) / 10, rows=int(mask.sum()),
                mean_probability=float(p[mask].mean()), observed_frequency=float(y[mask].mean())))
    return dict(available=True, rows=len(y), positive_rows=positives, negative_rows=len(y) - positives,
        prevalence=float(y.mean()), log_loss=float(-np.mean(y * np.log(clipped) + (1-y) * np.log1p(-clipped))),
        brier=float(np.square(p-y).mean()), auc=auc, accuracy=float(np.mean((p >= .5) == y)),
        calibration_bins=bins,
        probability_histogram=[dict(lower=i / 10, upper=(i + 1) / 10,
            rows=int(np.sum((p >= i / 10) & ((p < (i + 1) / 10) if i < 9 else (p <= 1))))) for i in range(10)],
        probability_quantiles={str(q): float(np.quantile(p, q)) for q in (0, .1, .5, .9, 1)})


def select_l2(frame, end, hurdle, spec, model_name):
    candidates = []
    for penalty in spec["l2_candidates"]:
        ys, ps, folds = [], [], []
        for begin, stop in inner_bounds(frame.start, end):
            training, validation = sample_indices(frame, frame.start, begin), sample_indices(frame, begin, stop)
            if not len(validation):
                raise ValueError("No eligible validation rows inside fixed chronological block")
            model = fit(frame, training, hurdle, penalty, begin, spec, model_name)
            y = (frame.future_return[validation] > hurdle).astype(int)
            p = predict(model, frame.x[validation])
            ys.extend(y.tolist()); ps.extend(p.tolist())
            folds.append(dict(start=iso(begin), end=iso(stop), training_rows=len(training),
                metrics=metrics(y, p), convergence=model["convergence"]))
        candidates.append(dict(l2_lambda=penalty, pooled=metrics(ys, ps), folds=folds))
    winner = min(candidates, key=lambda row: (row["pooled"]["log_loss"], -row["l2_lambda"]))
    return winner["l2_lambda"], dict(model_name=model_name, training_end=iso(end), candidates=candidates,
        selected_l2_lambda=winner["l2_lambda"], tie_rule="exact ties prefer stronger L2")


def paper(frame, indices, probabilities, begin, end, spec, buy_hold=False, cost=None):
    """Next-close fills; labels never gate entry, and exits can be unresolved."""
    n, first = (end - begin) // HOUR, (begin - frame.start) // HOUR
    nav = np.full(n + 1, np.nan)
    signals = dict(zip(map(int, indices), map(float, probabilities)))
    cash, position, pending, trades, unresolved, unfilled = 1.0, None, None, [], [], []
    missing_marks, invested = 0, 0
    cost = spec["round_trip_cost"] if cost is None else cost
    for offset in range(n + 1):
        i, exited = first + offset, False
        price = frame.xmr[i]
        valid = np.isfinite(price) and price > 0
        if position is not None and i == position["exit_index"]:
            if not valid:
                unresolved.append(dict(entry_time=iso(frame.start + position["entry_index"] * HOUR),
                    signal_time=iso(frame.start + position["signal_index"] * HOUR),
                    scheduled_exit=iso(frame.start + i * HOUR), reason="missing_or_stale_scheduled_exit",
                    selected_incident_id=position["incident_id"]))
                break
            gross = float(price / position["entry_price"] - 1)
            cash += position["notional"] * (1 + gross - cost)
            trades.append(dict(entry_time=iso(frame.start + position["entry_index"] * HOUR),
                signal_time=iso(frame.start + position["signal_index"] * HOUR),
                exit_time=iso(frame.start + i * HOUR), initial_notional=position["notional"],
                gross_return=gross, net_return=gross - cost, selected_incident_id=position["incident_id"]))
            position, exited = None, True
        if pending is not None and i == pending["fill_index"]:
            if valid:
                notional = cash * (1.0 if buy_hold else spec["paper_notional_fraction"])
                cash -= notional
                position = dict(notional=notional, entry_price=float(price), entry_index=i,
                    signal_index=pending["signal_index"], exit_index=pending["exit_index"],
                    incident_id=frame.audit[pending["signal_index"]]["selected_incident_id"])
            else:
                unfilled.append(dict(signal_time=iso(frame.start + pending["signal_index"] * HOUR),
                    scheduled_fill=iso(frame.start + i * HOUR), reason="missing_or_unreviewed_scheduled_fill"))
            pending = None
        if position is None:
            nav[offset] = cash
        elif valid:
            nav[offset] = cash + position["notional"] * float(price / position["entry_price"]) - cost * position["notional"]
        else:
            missing_marks += 1
        # An ending boundary price is usable for an exit, but not a new entry.
        permitted = offset < n and not exited and position is None and pending is None and valid
        fire = offset == 0 if buy_hold else signals.get(i, -1) >= spec["paper_entry_probability"] and frame.eligible[i]
        fill_i = i + spec["paper_fill_delay_hours"]
        exit_i = first + n if buy_hold else fill_i + spec["horizon_hours"]
        if permitted and fire and exit_i <= first + n:
            pending = dict(signal_index=i, fill_index=fill_i, exit_index=exit_i)
        if position is not None and offset < n:
            invested += 1
    if buy_hold and not trades and not unresolved:
        unresolved.append(dict(entry_time=iso(begin), scheduled_exit=iso(end), reason="missing_buy_hold_entry"))
    complete = not unresolved and position is None and pending is None and np.isfinite(nav[-1])
    finite = nav[np.isfinite(nav)]
    # Include initial equity 1 before reserving the additive round-trip cost.
    marked = np.r_[1.0, finite]
    drawdown = float(np.max(1 - marked / np.maximum.accumulate(marked)))
    end_nav = float(nav[-1]) if complete else None
    daily_offsets = np.unique(np.r_[np.arange(0, n + 1, 24), n])
    days = n / 24
    result = dict(completed_trades=len(trades), unresolved_trades=len(unresolved), unfilled_orders=len(unfilled),
        incident_associated_entries=sum(bool(t["selected_incident_id"]) for t in trades) + sum(bool(t.get("selected_incident_id")) for t in unresolved),
        missing_hourly_marks=missing_marks, complete=bool(complete), risk_complete=bool(complete and missing_marks == 0),
        net_return=end_nav - 1 if complete else None, maximum_drawdown_observed=drawdown,
        maximum_drawdown=drawdown if complete and not missing_marks else None,
        mean_daily_log_return=math.log(end_nav) / days if complete and end_nav > 0 and days else None,
        time_invested=invested / n if n else 0, initial_notional_fraction=1.0 if buy_hold else spec["paper_notional_fraction"],
        round_trip_cost=cost, fill_delay_hours=spec["paper_fill_delay_hours"],
        return_clock="Fill at next completed hourly close; exit 120 hours after fill (buy-and-hold: block end). Forecast labels retain decision-close clock.",
        mark_cost_convention="Reserve the full 2% round-trip cost against initial notional at entry; deduct it once on settlement.")
    curve = [dict(timestamp=iso(begin + int(o) * HOUR), equity=float(nav[o]) if np.isfinite(nav[o]) else None) for o in daily_offsets]
    result["unfilled_order_ledger"] = unfilled
    return result, trades, unresolved, curve


def incident_summary(frame, indices):
    windows = {}
    overlapping = 0
    for i in indices:
        row = frame.audit[i]
        overlapping += len(row["active_incident_ids"]) > 1
        for identity in row["active_incident_ids"]:
            windows.setdefault(identity, []).append(int(frame.times[i]))
    return dict(distinct_incidents=len(windows), canonical_incident_ids=sorted(windows),
        incident_hour_counts={key: len(value) for key, value in sorted(windows.items())},
        identity_unit="Existing provisional catalog group; not an independently verified attack",
        overlapping_active_incident_hours=int(overlapping), independent_hourly_trials=False)


def score_groups(frame, indices, y, p):
    active = frame.x[indices, 5] == 1
    return dict(overall=metrics(y, p), active_incident=metrics(y[active], p[active]),
        ordinary=metrics(y[~active], p[~active]), incidents=incident_summary(frame, indices))


def calibration_svg(comparisons):
    """Export reliability curves without requiring a plotting dependency."""
    colors = {"prevalence": "#6b7280", "market": "#2563eb", "presence": "#d97706", "full_incident": "#059669"}
    width, origin, size = 560, 65, 400
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="555" viewBox="0 0 {width} 555">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<g font-family="sans-serif" font-size="12" fill="#111827">',
        '<text x="65" y="25" font-size="16">Calibration on identical eligible evaluation rows</text>']
    for i in range(6):
        v = i / 5
        x, y = origin + v * size, origin + (1-v) * size
        parts.extend([f'<path d="M{x} {origin} V{origin+size} M{origin} {y} H{origin+size}" stroke="#e5e7eb" fill="none"/>',
            f'<text x="{x}" y="{origin+size+20}" text-anchor="middle">{v:.1f}</text>',
            f'<text x="{origin-10}" y="{y+4}" text-anchor="end">{v:.1f}</text>'])
    parts.extend([f'<path d="M{origin} {origin+size} L{origin+size} {origin}" stroke="#9ca3af" stroke-dasharray="5 5" fill="none"/>',
        '<text x="265" y="505" text-anchor="middle">Mean predicted probability</text>',
        '<text transform="translate(18 265) rotate(-90)" text-anchor="middle">Observed positive frequency</text>'])
    for number, (name, color) in enumerate(colors.items()):
        bins = comparisons[name]["calibration_bins"]
        points = [(origin + b["mean_probability"] * size, origin + (1-b["observed_frequency"]) * size) for b in bins]
        path = " ".join(f"{x:.3f},{y:.3f}" for x, y in points)
        parts.append(f'<polyline points="{path}" stroke="{color}" fill="none" stroke-width="2"/>')
        for x, y in points:
            parts.append(f'<circle cx="{x:.3f}" cy="{y:.3f}" r="3" fill="{color}"/>')
        x = 35 + number * 135
        parts.append(f'<text x="{x}" y="535" fill="{color}">{name}</text>')
    return ("\n".join(parts + ["</g></svg>"]) + "\n").encode()


def block_uncertainty(times, y, p, reference, spec):
    if not len(times):
        return dict(available=False, reason="No common evaluation rows")
    block_ids = (times - times[0]) // (spec["uncertainty_block_hours"] * HOUR)
    # Merge a terminal calendar fragment shorter than the five-day horizon.
    # Missing observations inside a calendar block never compress its duration.
    unique = np.unique(block_ids)
    terminal_duration = (times[-1] + HOUR - (times[0] + unique[-1] * spec["uncertainty_block_hours"] * HOUR)) / HOUR
    terminal_merged = len(unique) > 1 and terminal_duration < 120
    if terminal_merged:
        block_ids[block_ids == unique[-1]] = unique[-2]
    blocks = [np.flatnonzero(block_ids == i) for i in np.unique(block_ids)]
    if len(blocks) < 2:
        return dict(available=False, reason="Fewer than two occupied calendar blocks")
    cp, cr = np.clip(p, 1e-15, 1 - 1e-15), np.clip(reference, 1e-15, 1 - 1e-15)
    delta_loss = -y * np.log(cp) - (1-y) * np.log1p(-cp) + y * np.log(cr) + (1-y) * np.log1p(-cr)
    delta_brier = (p-y)**2 - (reference-y)**2
    sums = np.array([[delta_loss[idx].sum(), delta_brier[idx].sum(), len(idx)] for idx in blocks])
    rng, draws = np.random.default_rng(spec["random_seed"]), []
    for _ in range(spec["bootstrap_replicates"]):
        total = sums[rng.integers(0, len(blocks), len(blocks))].sum(axis=0)
        draws.append(total[:2] / total[2])
    draws = np.asarray(draws)
    return dict(available=True, calendar_blocks=len(blocks), block_hours=spec["uncertainty_block_hours"],
        replicates=spec["bootstrap_replicates"], terminal_fragment_merged=bool(terminal_merged),
        log_loss_difference_95pct=np.quantile(draws[:, 0], [.025, .975]).tolist(),
        brier_difference_95pct=np.quantile(draws[:, 1], [.025, .975]).tolist(),
        interpretation="Paired model-minus-reference calendar-block intervals; negative favors model. Approximate serial-dependence uncertainty, not independent hourly confidence intervals.")


def run(spec, root=ROOT, verify_only=False):
    verify_training_freeze(spec, root)
    folder = root / OUT / "results"
    if not verify_only and folder.exists() and any(folder.iterdir()):
        raise ValueError("Refusing to overwrite existing results")
    frame = load_frame(spec, root, outcomes=True)
    if not readiness(frame, spec)["initial_selection_ready"]:
        raise ValueError("Initial selection data readiness failed")
    initial = timestamp(spec["initial_development_end"])
    selection = inherited_selection(spec, root)
    hurdle = selection["selected_hurdle"]
    # Must be persisted BEFORE the first outer fit/score.
    selected_path = root / OUT / "SELECTED.json"
    selected = json_bytes(dict(selection=selection, config=spec, feature_names=FEATURES,
        selection_end=iso(initial), pre_fit_freeze_sha256=digest(root / OUT / "FROZEN.json")))
    if selected_path.exists():
        if selected_path.read_bytes() != selected:
            raise ValueError("Frozen selected hurdle/policy differs")
    elif verify_only:
        raise ValueError("Missing pre-outer SELECTED.json")
    else:
        selected_path.write_bytes(selected)
    outputs, reports, rows, parts = {}, [], [], []
    begin = initial
    for number, end_text in enumerate(spec["outer_ends"], 1):
        end = timestamp(end_text)
        training, indices = sample_indices(frame, frame.start, begin), sample_indices(frame, begin, end)
        if not len(indices):
            raise ValueError("No eligible outer test rows in frozen block")
        y = (frame.future_return[indices] > hurdle).astype(int)
        probabilities = {"prevalence": np.full(len(indices), float((frame.future_return[training] > hurdle).mean()))}
        report = dict(fold=number, start=iso(begin), end_exclusive=iso(end), training_rows=len(training), comparisons={})
        trading = np.flatnonzero((frame.times >= begin) & (frame.times < end) & frame.eligible)
        for name in MODELS:
            if not verify_only:
                print(f"Outer {number}: selecting inner L2 and fitting {name} on {len(training)} training rows; {len(indices)} paired test rows", flush=True)
            penalty, inner = select_l2(frame, begin, hurdle, spec, name)
            model = fit(frame, training, hurdle, penalty, begin, spec, name)
            probabilities[name] = predict(model, frame.x[indices])
            policy, trades, unresolved, curve = paper(frame, trading, predict(model, frame.x[trading]), begin, end, spec)
            stress, stress_trades, stress_unresolved, stress_curve = paper(frame, trading, predict(model, frame.x[trading]), begin, end, spec, cost=2 * spec["round_trip_cost"])
            report["comparisons"][name] = dict(selected_l2_lambda=penalty,
                probability=score_groups(frame, indices, y, probabilities[name]), paper_policy=policy, double_cost_stress=stress)
            outputs[f"models/fold_{number}_{name}.json"] = json_bytes(model)
            outputs[f"inner/fold_{number}_{name}.json"] = json_bytes(inner)
            outputs[f"paper/fold_{number}_{name}.json"] = json_bytes(dict(policy=policy, trades=trades, unresolved=unresolved, daily_equity=curve))
            outputs[f"paper/fold_{number}_{name}_double_cost.json"] = json_bytes(dict(policy=stress, trades=stress_trades, unresolved=stress_unresolved, daily_equity=stress_curve))
        report["comparisons"]["prevalence"] = dict(probability=score_groups(frame, indices, y, probabilities["prevalence"]))
        outputs[f"calibration/fold_{number}.svg"] = calibration_svg({name: data["probability"]["overall"] for name, data in report["comparisons"].items()})
        buy_hold, bt, bu, curve = paper(frame, np.array([], dtype=int), np.array([]), begin, end, spec, buy_hold=True)
        report["buy_and_hold"] = dict(**buy_hold, exposure_disclosure="100% initial XMR notional across the block versus 10% per five-day model trade; same 2% additive round-trip cost.")
        report["cash"] = dict(net_return=0.0, maximum_drawdown=0.0, time_invested=0.0)
        outputs[f"paper/fold_{number}_buy_hold.json"] = json_bytes(dict(policy=report["buy_and_hold"], trades=bt, unresolved=bu, daily_equity=curve))
        report["uncertainty"] = {name + "_minus_market": block_uncertainty(frame.times[indices], y, probabilities[name], probabilities["market"], spec) for name in ("presence", "full_incident")}
        for i, target in zip(indices, y):
            at = int(np.searchsorted(indices, i))
            rows.append(dict(fold=number, decision_time=iso(frame.times[i]), target_end=iso(frame.times[i] + 120 * HOUR),
                gross_return=float(frame.future_return[i]), target=int(target), selected_incident_id=frame.audit[i]["selected_incident_id"],
                incident_active=int(frame.x[i, 5]), **{name + "_probability": float(p[at]) for name, p in probabilities.items()}))
        reports.append(report)
        parts.append((indices, y, probabilities))
        begin = end
    pooled_indices = np.concatenate([p[0] for p in parts])
    pooled_y = np.concatenate([p[1] for p in parts])
    pooled_p = {name: np.concatenate([p[2][name] for p in parts]) for name in ("prevalence", *MODELS)}
    final_models = {}
    for name in MODELS:
        if not verify_only:
            print(f"Final development fit: selecting inner L2 for {name}", flush=True)
        penalty, inner = select_l2(frame, frame.cutoff, hurdle, spec, name)
        model = fit(frame, sample_indices(frame, frame.start, frame.cutoff), hurdle, penalty, frame.cutoff, spec, name)
        final_models[name] = model
        outputs[f"models/final_{name}.json"] = json_bytes(model)
        outputs[f"inner/final_{name}.json"] = json_bytes(inner)
    final_freeze = dict(models=final_models, selected_hurdle=hurdle, policy=spec,
        pre_run_sha256=digest(root / OUT / "PRE_RUN.json"), selected_sha256=digest(selected_path),
        source_code_hashes=verify_inputs(spec, root)["input_sha256"], prior_inspection_disclosure=DISCLOSURE,
        amendment_timing_disclosure=AMENDMENT_DISCLOSURE, incident_mode=spec["incident_mode"],
        reserved_outcomes_scored=False)
    summary = dict(study_id=spec["study_id"], selected_hurdle=hurdle,
        economically_supported_hurdle=selection["economically_supported_hurdle"], fallback_used=selection["fallback_used"],
        outer_folds=reports, pooled={name: score_groups(frame, pooled_indices, pooled_y, p) for name, p in pooled_p.items()},
        uncertainty={name + "_minus_" + reference: block_uncertainty(frame.times[pooled_indices], pooled_y, pooled_p[name], pooled_p[reference], spec)
            for name, reference in (("market", "prevalence"), ("presence", "market"), ("full_incident", "market"))},
        reserved_outcomes_scored=False, prior_inspection_disclosure=DISCLOSURE,
        amendment_timing_disclosure=AMENDMENT_DISCLOSURE, incident_mode=spec["incident_mode"],
        baseline_comparator_refitted=True, hurdle_selection_repeated=False,
        paired_cohort_check=json.loads((root / OUT / "PAIRED_COHORT_CHECK.json").read_text()),
        independence_warning="Neighboring five-day hourly labels share 119/120 intervals. Active hours do not multiply distinct incidents.")
    lines = ["# Retrospective catalog-date incident comparison", "", DISCLOSURE, "", AMENDMENT_DISCLOSURE, "",
        f"Frozen hurdle: {hurdle:.0%}. Economically supported selection: {selection['economically_supported_hurdle']}.", "",
        "| Comparison | Pooled rows | Log loss | Brier | AUC | Accuracy |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, group in summary["pooled"].items():
        m = group["overall"]
        auc = "unavailable" if m["auc"] is None else f"{m['auc']:.4f}"
        lines.append(f"| {name} | {m['rows']} | {m['log_loss']:.4f} | {m['brier']:.4f} | {auc} | {m['accuracy']:.2%} |")
    lines += ["", "| Outer block | Comparison | Rows | L2 | Log loss | Brier | AUC | Accuracy |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for report in reports:
        for name, comparison in report["comparisons"].items():
            metric = comparison["probability"]["overall"]
            auc = "unavailable" if metric["auc"] is None else f"{metric['auc']:.4f}"
            lines.append(f"| {report['fold']} | {name} | {metric['rows']} | {comparison.get('selected_l2_lambda', 'constant')} | {metric['log_loss']:.4f} | {metric['brier']:.4f} | {auc} | {metric['accuracy']:.2%} |")
    lines += ["", "Catalog activation is assumed at next-day UTC midnight. Frozen reported losses and catalog absence are retrospective proxies; unavailable detection/publication fields remain unchanged.",
        "The baseline's saved 3% fallback was inherited without any new hurdle search. Every comparator was refitted on exactly the same training/test population."]
    lines.extend(["", "See summary.json for each outer block, incident/ordinary groups, calibration curves, probability distributions, paper returns, unresolved exits, drawdown, exposure and paired 168-hour uncertainty.",
        "No reserved outcomes were evaluated. The fallback, if used, is descriptive and supplies no claim of a tradable edge.", ""])
    outputs.update({"summary.json": json_bytes(summary), "hurdle_selection.json": json_bytes(selection),
        "FINAL_FROZEN.json": json_bytes(final_freeze), "RESULTS.md": "\n".join(lines).encode(),
        "calibration/pooled.svg": calibration_svg({name: data["overall"] for name, data in summary["pooled"].items()}),
        "outer_predictions.csv": csv_bytes(rows, list(rows[0]))})
    verify_training_freeze(spec, root)
    manifest = dict(pre_run_sha256=digest(root / OUT / "PRE_RUN.json"), selected_sha256=digest(selected_path),
        training_freeze_sha256=digest(root / OUT / "FROZEN.json"),
        runtime=dict(python=platform.python_version(), numpy=np.__version__), reserved_outcomes_scored=False,
        output_sha256={path: hashlib.sha256(data).hexdigest() for path, data in outputs.items()})
    for path, data in outputs.items():
        dest = folder / path
        if verify_only:
            if dest.read_bytes() != data:
                raise ValueError("Run reproduction mismatch: " + path)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
    if verify_only:
        if json.loads((folder / "RUN.json").read_text()) != manifest:
            raise ValueError("Run manifest mismatch")
    else:
        (folder / "RUN.json").write_bytes(json_bytes(manifest))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    sub.add_parser("freeze")
    sub.add_parser("verify")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    spec = DEFAULT_SPEC
    try:
        if args.command == "prepare":
            result = prepare(spec)
        elif args.command == "verify":
            result = prepare(spec, verify_only=True)
        elif args.command == "freeze":
            freeze(spec)
            result = dict(status="training_freeze_written")
        else:
            result = run(spec, verify_only=args.verify)
            result = {key: result[key] for key in ("selected_hurdle", "economically_supported_hurdle", "reserved_outcomes_scored")}
        print(json.dumps(result, indent=2, allow_nan=False))
    except ValueError as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    main()
