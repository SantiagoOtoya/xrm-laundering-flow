"""Price-only hourly logistic baseline derived from NEWMODELS.MD.

Commands: prepare (source/price review), check (read-only eligibility), freeze,
run. Source/price-review rules are recorded before any model outcomes.
The reserved OOS period cannot be evaluated by this script. Forecast labels
retain the document's completed-close clock; simulated trades fill one hour
later and hold for 120 hours from that fill. No incident files are accessed.
"""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
import platform
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CONFIG = "config/models/xmr_hourly_price_baseline_v1.json"
OUT = "docs/models/xmr_hourly_price_baseline_v1"
HOUR = 3600
FEATURES = ["xmr_return_24h", "xmr_return_preceding_6d", "btc_return_24h",
            "btc_return_preceding_6d", "xmr_realized_volatility_24h"]
DISCLOSURE = "Reserved historical outcomes were inspected previously; this is not a pristine holdout."


def timestamp(value):
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() != dt.timedelta(0) or parsed.minute or parsed.second or parsed.microsecond:
        raise ValueError("Expected an exact UTC hour: " + value)
    return int(parsed.timestamp())


def iso(value):
    return dt.datetime.fromtimestamp(int(value), dt.timezone.utc).isoformat().replace("+00:00", "Z")


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def csv_bytes(rows, fields):
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue().encode()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_spec(spec):
    start = timestamp(spec["history_start"])
    end = timestamp(spec["history_end_exclusive"])
    cutoff = timestamp(spec["development_end_exclusive"])
    # Calendar allocation is fixed before quality filtering, rounded up to a day.
    days = (end - start) // (24 * HOUR)
    if end - start != days * 24 * HOUR or cutoff != end - math.ceil(days / 5) * 24 * HOUR:
        raise ValueError("The last 20% of calendar history must remain reserved")
    development_hours = (cutoff - start) // HOUR
    initial = timestamp(spec["initial_development_end"])
    if initial != start + development_hours // 2 * HOUR:
        raise ValueError("Initial allocation must be half of development")
    expected = [initial + (cutoff - initial) // HOUR * i // 3 * HOUR for i in (1, 2, 3)]
    if list(map(timestamp, spec["outer_ends"])) != expected:
        raise ValueError("Outer blocks must be three equal calendar allocations")
    if spec["horizon_hours"] != 120 or spec["paper_fill_delay_hours"] != 1:
        raise ValueError("Fixed five-day horizon and later-bar fills required")
    if spec["reserved_period_evaluation_allowed"] or not spec["prior_holdout_inspection_disclosed"]:
        raise ValueError("OOS evaluation is disabled and prior inspection must be disclosed")
    if min(spec["l2_candidates"]) <= 0 or spec["fallback_hurdle"] not in spec["hurdle_candidates"]:
        raise ValueError("Invalid fixed selection grids")
    if spec["uncertainty_block_hours"] < spec["horizon_hours"]:
        raise ValueError("Uncertainty blocks must be at least 120 hours")
    return start, cutoff


def read_closes(path, start, cutoff, maximum_age, excluded_bar_starts=()):
    """Filter timestamp BEFORE numeric parsing; no OOS OHLC/volume is parsed.

    P(t) is the close of the bar starting t-1h. P(cutoff) is permitted: its
    trades precede cutoff. Raw full-source hashes include OOS bytes for provenance
    only; their prices are never used as model inputs or outcomes.
    """
    prices = np.full((cutoff - start) // HOUR + 1, np.nan)
    excluded = set(excluded_bar_starts)
    previous = None
    with Path(path).open(newline="") as handle:
        for row in csv.DictReader(handle):
            bar_start = int(row["timestamp_unix"])
            if previous is not None and bar_start <= previous:
                raise ValueError("Hourly source must have unique chronological timestamps")
            previous = bar_start
            if bar_start >= cutoff:
                break
            if bar_start < start:
                continue
            if (bar_start - start) % HOUR or timestamp(row["timestamp_utc"]) != bar_start:
                raise ValueError("Inconsistent hourly timestamp")
            if "available_after_utc" in row and timestamp(row["available_after_utc"]) != bar_start + HOUR:
                raise ValueError("Combined price must use its completed-hour boundary")
            if bar_start in excluded:
                continue
            if not row["close_usd"] or not row["close_age_seconds"]:
                continue
            close, age = float(row["close_usd"]), float(row["close_age_seconds"])
            if "close_usd_source" in row:
                if row["close_usd_source"] not in ("kraken_xmr_usd", "binance_xmr_btc_times_kraken_btc_usd"):
                    raise ValueError("Unexpected combined price source")
                minute = timestamp_minute(row["close_usd_minute_utc"])
                if not bar_start <= minute < bar_start + HOUR or age != bar_start + HOUR - minute:
                    raise ValueError("Selected price minute/age differs from completed-hour timing")
            if math.isfinite(close) and close > 0 and math.isfinite(age) and 60 <= age <= maximum_age:
                prices[(bar_start + HOUR - start) // HOUR] = close
    return prices


def timestamp_minute(value):
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() != dt.timedelta(0) or parsed.second or parsed.microsecond:
        raise ValueError("Expected an exact UTC minute: " + value)
    return int(parsed.timestamp())


def verify_price_sources(spec, root=ROOT):
    """Compare full-file hashes with existing source/independent-validation manifests.

    Full hashes are provenance checks; no reserved numerical values are analyzed.
    """
    checks = [("xmr_path", "xmr_coverage_path", "sha256_csv"),
              ("btc_path", "btc_coverage_path", "sha256_csv"),
              ("xmr_path", "xmr_validation_path", "csv_sha256"),
              ("btc_path", "btc_validation_path", "hourly_sha256_csv")]
    hashes = {k:digest(root / spec[k]) for k in ("xmr_path", "btc_path")}
    reports = {}
    for source, manifest, field in checks:
        if manifest in spec:
            evidence = json.loads((root / spec[manifest]).read_text())
            if evidence[field] != hashes[source]:
                raise ValueError("Source differs from its validation manifest: " + spec[source])
            reports[manifest] = dict(path=spec[manifest], sha256=digest(root / spec[manifest]),
                                     source_sha256=hashes[source], matched=True)
    return reports


def review_rows(spec, root=ROOT):
    """Only contemporaneous within-hour metadata; no subsequent returns or OOS fields."""
    start, cutoff = validate_spec(spec)
    rows, sources, switches = [], Counter(), 0
    with (root / spec["xmr_path"]).open(newline="") as handle:
        for row in csv.DictReader(handle):
            t = int(row["timestamp_unix"])
            if t >= cutoff:
                break
            if t < start:
                continue
            if row.get("close_usd_source"):
                sources[row["close_usd_source"]] += 1
            switches += int(row.get("close_source_changed_from_prior_hour", "0") or 0)
            if row.get("needs_price_review") != "1":
                continue
            rows.append(dict(bar_start=iso(t), price_boundary=iso(t + HOUR),
                selected_source=row["close_usd_source"], selected_minute=row["close_usd_minute_utc"],
                within_hour_maximum_venue_difference_pct=row["max_shared_minute_absolute_difference_pct"],
                selected_close_venue_difference_pct=row["selected_usd_close_shared_difference_pct"] or None,
                disposition="unresolved", action="exclude_required_close",
                reason="Publisher/import verification does not resolve flagged venue-price disagreement. No independent selected-close disposition exists; retain raw data, withhold this close from features, targets and simulated fills."))
    return rows, dict(development_selected_sources=dict(sources), development_source_switches=switches,
        assessment="Source changes may contribute to measured returns/volatility. The predeclared conversion priority is retained; switching is audit metadata, not a model feature or a reason to optimize source selection.")


def prepare_review(spec, root=ROOT):
    sources = verify_price_sources(spec, root)
    rows, switching = review_rows(spec, root)
    ledger = dict(study_id=spec["study_id"], xmr_source_sha256=digest(root / spec["xmr_path"]),
        development_end_exclusive=spec["development_end_exclusive"],
        policy="Unresolved/invalid required prices excluded; no price replacement, relaxed freshness or score-based review.",
        no_model_outcomes_used=True, no_subsequent_returns_used=True, oos_numeric_values_parsed=False,
        source_verification=sources, source_switch_review=switching,
        disposition_counts=dict(Counter(r["disposition"] for r in rows)), rows=rows)
    path = root / spec["price_review_path"]
    data = json_bytes(ledger)
    if path.exists() and path.read_bytes() != data:
        raise ValueError("Refusing to replace a different price review")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return ledger


def excluded_review_prices(spec, root=ROOT):
    if "price_review_path" not in spec:
        return set(), []
    ledger = json.loads((root / spec["price_review_path"]).read_text())
    if ledger["xmr_source_sha256"] != digest(root / spec["xmr_path"]):
        raise ValueError("Price review belongs to a different source snapshot")
    if ledger["development_end_exclusive"] != spec["development_end_exclusive"]:
        raise ValueError("Price review uses a different development boundary")
    current, _ = review_rows(spec, root)
    records = {r["bar_start"]:r for r in ledger["rows"]}
    if len(records) != len(ledger["rows"]) or set(records) != {r["bar_start"] for r in current}:
        raise ValueError("All flagged development prices need unique explicit dispositions")
    excluded = set()
    for key, record in records.items():
        if record["disposition"] not in ("accepted", "invalid", "unresolved") or not record["reason"]:
            raise ValueError("Invalid price review disposition")
        if record["disposition"] != "accepted":
            excluded.add(timestamp(key))
    return excluded, ledger["rows"]


@dataclass
class Frame:
    start: int
    cutoff: int
    xmr: np.ndarray
    btc: np.ndarray
    x: np.ndarray
    future_return: np.ndarray
    exclusions: list

    @property
    def times(self):
        return self.start + np.arange(len(self.x), dtype=np.int64) * HOUR

    @property
    def eligible(self):
        return np.isfinite(self.x).all(axis=1)


def build_frame(xmr, btc, start, cutoff, horizon=120):
    n = (cutoff - start) // HOUR
    if len(xmr) != n + 1 or len(btc) != n + 1:
        raise ValueError("Prices must use the same complete calendar grid")
    x, outcomes, exclusions = np.full((n, 5), np.nan), np.full(n, np.nan), []
    for i in range(n):
        reason = None
        if i < 168:
            reason = "incomplete_7day_feature_history"
        elif not np.isfinite(xmr[i - 24:i + 1]).all() or not np.isfinite(xmr[i - 168]):
            reason = "missing_or_stale_xmr_feature_price"
        elif not np.isfinite(btc[[i, i - 24, i - 168]]).all():
            reason = "missing_or_stale_btc_feature_price"
        else:
            x[i] = [math.log(xmr[i] / xmr[i - 24]), math.log(xmr[i - 24] / xmr[i - 168]),
                    math.log(btc[i] / btc[i - 24]), math.log(btc[i - 24] / btc[i - 168]),
                    float(np.sqrt(np.square(np.diff(np.log(xmr[i - 24:i + 1]))).sum()))]
        if reason:
            exclusions.append(dict(decision_time=iso(start + i * HOUR), reason=reason))
        # Outcome eligibility NEVER gates the feature frame or simulated entries.
        if i + horizon <= n and np.isfinite(xmr[i]) and np.isfinite(xmr[i + horizon]):
            outcomes[i] = xmr[i + horizon] / xmr[i] - 1
        if reason is None and not np.isfinite(outcomes[i]):
            exclusions.append(dict(decision_time=iso(start + i * HOUR),
                reason="crosses_development_boundary" if i + horizon > n else "missing_or_stale_target_endpoint"))
    return Frame(start, cutoff, xmr, btc, x, outcomes, exclusions)


def load_frame(spec, root=ROOT):
    start, cutoff = validate_spec(spec)
    excluded, reviews = excluded_review_prices(spec, root)
    frame = build_frame(read_closes(root / spec["xmr_path"], start, cutoff,
                        spec["maximum_close_age_seconds"], excluded),
                        read_closes(root / spec["btc_path"], start, cutoff, spec["maximum_close_age_seconds"]),
                        start, cutoff, spec["horizon_hours"])
    # Add source-review causes alongside downstream missing/stale exclusions.
    frame.exclusions.extend(dict(decision_time=r["price_boundary"],
        reason="unresolved_or_invalid_xmr_required_price") for r in reviews if r["disposition"] != "accepted")
    return frame


def sample_indices(frame, begin, end, horizon=120):
    """Timestamp-based target purge, including exact label-end equality."""
    t = frame.times
    return np.flatnonzero((t >= begin) & (t < end) & (t + horizon * HOUR <= end)
                         & frame.eligible & np.isfinite(frame.future_return))


def inner_bounds(start, end):
    hours = (end - start) // HOUR
    middle = start + hours // 2 * HOUR
    rest = (end - middle) // HOUR
    bounds = [middle + rest * i // 3 * HOUR for i in range(4)]
    return list(zip(bounds, bounds[1:]))


def sigmoid(z):
    # Clipping here only prevents exp overflow, not fitting/probability censoring.
    return np.exp(-np.logaddexp(0.0, -z))


def fit(frame, indices, hurdle, penalty, end, spec):
    if not len(indices) or np.any(frame.times[indices] + spec["horizon_hours"] * HOUR > end):
        raise ValueError("Empty training sample or outcome crossing training cutoff")
    raw = frame.x[indices]
    y = (frame.future_return[indices] > hurdle).astype(float)
    if len(np.unique(y)) != 2:
        raise ValueError("Training requires both target classes")
    mean, scale = raw.mean(axis=0), raw.std(axis=0)
    constant = scale <= 1e-12
    scale = np.where(constant, 1.0, scale)
    a = np.column_stack((np.ones(len(indices)), (raw - mean) / scale))
    theta = np.zeros(a.shape[1])
    theta[0] = math.log(y.mean() / (1 - y.mean()))
    regularizer = np.diag([0.0] + [penalty] * len(FEATURES))

    def loss(v):
        logits = a @ v
        return float(np.mean(np.logaddexp(0, logits) - y * logits) + .5 * penalty * np.square(v[1:]).sum())

    for iteration in range(spec["optimizer_max_iterations"]):
        p = sigmoid(a @ theta)
        gradient = a.T @ (p - y) / len(y) + regularizer @ theta
        if np.max(np.abs(gradient)) <= spec["optimizer_gradient_tolerance"]:
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
    final_p = sigmoid(a @ theta)
    gradient = a.T @ (final_p - y) / len(y) + regularizer @ theta
    if np.max(np.abs(gradient)) > spec["optimizer_gradient_tolerance"]:
        raise ValueError("Optimizer failed convergence tolerance")
    return dict(feature_names=FEATURES, scaler_mean=mean.tolist(), scaler_scale=scale.tolist(),
        constant_training_features=[f for f, is_constant in zip(FEATURES, constant) if is_constant],
        intercept=float(theta[0]), coefficients=theta[1:].tolist(), hurdle=hurdle, l2_lambda=penalty,
        training_rows=len(indices), training_prevalence=float(y.mean()), training_end_exclusive=iso(end),
        target="Completed-close gross XMR/USD 120-hour simple return strictly greater than hurdle",
        incident_inputs_used=False, objective="mean BCE + lambda/2 * sum(beta squared); intercept unpenalized",
        convergence=dict(iterations=iteration + 1, gradient_linf=float(np.abs(gradient).max()), objective=loss(theta)))


def predict(model, x):
    return sigmoid((x - np.asarray(model["scaler_mean"])) / np.asarray(model["scaler_scale"])
                   @ np.asarray(model["coefficients"]) + model["intercept"])


def metrics(y, p):
    if not len(y):
        raise ValueError("Cannot score an empty evaluation sample")
    y, p = np.asarray(y), np.asarray(p)
    if not np.isfinite(p).all() or np.any((p < 0) | (p > 1)):
        raise ValueError("Invalid probabilities")
    clipped = np.clip(p, 1e-15, 1 - 1e-15)
    auc = None
    positives = int(y.sum())
    if 0 < positives < len(y):
        order = np.argsort(p, kind="stable")
        ordered_p = p[order]
        lo = np.r_[0, np.flatnonzero(np.diff(ordered_p)) + 1]
        hi = np.r_[lo[1:], len(y)]
        ranks = np.empty(len(y), dtype=float)
        for first, last in zip(lo, hi):
            ranks[order[first:last]] = (first + 1 + last) / 2
        auc = float((ranks[y == 1].sum() - positives * (positives + 1) / 2) / (positives * (len(y) - positives)))
    bins = []
    for i in range(10):
        mask = (p >= i / 10) & ((p < (i + 1) / 10) if i < 9 else (p <= 1))
        if mask.any():
            bins.append(dict(lower=i / 10, upper=(i + 1) / 10, rows=int(mask.sum()),
                             mean_probability=float(p[mask].mean()), observed_frequency=float(y[mask].mean())))
    return dict(rows=len(y), positive_rows=positives, prevalence=float(y.mean()),
        log_loss=float(-np.mean(y * np.log(clipped) + (1 - y) * np.log1p(-clipped))),
        brier=float(np.square(p - y).mean()), auc=auc, accuracy=float(np.mean((p >= .5) == y)),
        calibration_bins=bins, probability_quantiles={str(q):float(np.quantile(p, q)) for q in (0, .1, .5, .9, 1)},
        probability_histogram=dict(edges=np.linspace(0,1,11).tolist(), counts=np.histogram(p,bins=np.linspace(0,1,11))[0].tolist()))


def select_l2(frame, end, hurdle, spec):
    """Accept a training end, never outer scores; every inner scaler is fitted anew."""
    candidates = []
    for penalty in spec["l2_candidates"]:
        ys, ps, fold_reports = [], [], []
        for begin, stop in inner_bounds(frame.start, end):
            training = sample_indices(frame, frame.start, begin)
            validation = sample_indices(frame, begin, stop)
            if not len(validation):
                raise ValueError("No eligible inner validation rows at " + iso(begin))
            model = fit(frame, training, hurdle, penalty, begin, spec)
            y = (frame.future_return[validation] > hurdle).astype(int)
            p = predict(model, frame.x[validation])
            ys.extend(y.tolist()); ps.extend(p.tolist())
            fold_reports.append(dict(training_end=iso(begin), validation_end=iso(stop),
                training_rows=len(training), validation=metrics(y, p), convergence=model["convergence"]))
        candidates.append(dict(l2_lambda=penalty, pooled=metrics(np.asarray(ys), np.asarray(ps)), folds=fold_reports))
    selected = min(candidates, key=lambda r:(r["pooled"]["log_loss"], -r["l2_lambda"]))
    return selected["l2_lambda"], dict(selected_l2_lambda=selected["l2_lambda"], training_end=iso(end),
        selection_metric="Pooled inner log loss; exact ties prefer stronger L2", candidates=candidates)


def paper(frame, indices, probabilities, begin, end, spec, cost=None, buy_hold=False):
    """Later-bar execution. Entries do not consult future target eligibility.

    Missing scheduled exits are unresolved trades, never retroactive deletions.
    Missing intermediate marks stay unknown and make risk assessment incomplete.
    Fees are charged half at each side on initial notional, exactly once.
    """
    cost = spec["round_trip_cost"] if cost is None else cost
    n = (end - begin) // HOUR
    nav = np.full(n + 1, np.nan); nav[0] = 1.0
    signals = dict(zip(indices.tolist(), np.asarray(probabilities).tolist()))
    cash, units, entry_price, notional, exit_index = 1.0, 0.0, None, None, None
    pending = None
    trades, unfilled, unresolved, missing_marks, invested = [], 0, 0, 0, 0
    turnover, signal_time = 0.0, None
    first_index = (begin - frame.start) // HOUR
    for offset in range(n + 1):
        i = first_index + offset
        price = frame.xmr[i]
        exited = False
        if units and i == exit_index:
            if not np.isfinite(price):
                unresolved += 1
                break
            cash += units * price - cost / 2 * notional
            trades.append(dict(signal_time=iso(signal_time), entry_time=iso(frame.start + entry_index * HOUR),
                exit_time=iso(frame.start + i * HOUR), initial_notional=notional,
                gross_return=float(price / entry_price - 1), net_return=float(price / entry_price - 1 - cost)))
            turnover += float(units * price / cash)
            units, exited = 0.0, True
        if pending == i:
            if not np.isfinite(price):
                unfilled += 1
            else:
                entry_price, entry_index = float(price), i
                notional = cash * spec["paper_notional_fraction"]
                if buy_hold:
                    notional = cash / (1 + cost / 2)
                turnover += notional / cash
                cash -= notional * (1 + cost / 2)
                units = notional / entry_price
                exit_index = first_index + n if buy_hold else i + spec["horizon_hours"]
            pending = None
        if units:
            invested += int(offset < n)
            if np.isfinite(price):
                nav[offset] = cash + units * price
            else:
                missing_marks += 1
        else:
            nav[offset] = cash
        # No same-timestamp re-entry. Future exit/fill quality does not gate a signal.
        can_enter = offset < n and not units and pending is None and not exited
        permitted = i + spec["paper_fill_delay_hours"] + spec["horizon_hours"] <= first_index + n
        if buy_hold:
            fire = offset == 0
        else:
            fire = signals.get(i, -1) >= spec["paper_entry_probability"] and permitted
        if can_enter and fire:
            pending = i + spec["paper_fill_delay_hours"]
            signal_time = frame.start + i * HOUR
    finite = nav[np.isfinite(nav)]
    drawdown = float(np.max(1 - finite / np.maximum.accumulate(finite))) if len(finite) else None
    complete = bool(unresolved == 0 and np.isfinite(nav[-1]))
    # Daily sampling stays anchored at the block's first UTC decision; partial final day is disclosed.
    daily_offsets = np.unique(np.r_[np.arange(0, n + 1, 24), n])
    daily = nav[daily_offsets]
    daily_returns = daily[1:] / daily[:-1] - 1
    valid_daily = daily_returns[np.isfinite(daily_returns)]
    days = n / 24
    end_nav = float(nav[-1]) if complete else None
    daily_complete = len(valid_daily) == len(daily_returns)
    mean_log = math.log(end_nav) / days if complete and end_nav > 0 and days else None
    std = float(valid_daily.std(ddof=1)) if len(valid_daily) > 1 else 0.0
    annualized = math.expm1(mean_log * 365) if mean_log is not None else None
    result = dict(completed_trades=len(trades), unresolved_trades=unresolved, unfilled_orders=unfilled,
        missing_hourly_marks=missing_marks, complete=complete, risk_complete=complete and missing_marks == 0,
        net_return=end_nav - 1 if end_nav is not None else None, mean_daily_log_return=mean_log,
        annualized_return=annualized, annualized_daily_volatility=std * math.sqrt(365) if daily_complete else None,
        daily_sharpe=float(valid_daily.mean() / std * math.sqrt(365)) if daily_complete and std > 0 else None,
        maximum_drawdown_observed=drawdown, annualized_turnover=turnover * 365 / days,
        time_invested=invested / n if n else 0, round_trip_cost=cost, fill_delay_hours=spec["paper_fill_delay_hours"],
        daily_sampling="24-hour intervals from block start; final partial interval retained",
        return_clock="120 hours from delayed fill; differs from completed-close forecast target")
    curve = [dict(timestamp=iso(begin + int(o) * HOUR), equity=float(nav[o]) if np.isfinite(nav[o]) else None)
             for o in daily_offsets]
    return result, trades, curve


def select_hurdle(frame, initial_end, spec):
    """Economic selection uses only A; target losses are not compared across hurdles."""
    reports = []
    for hurdle in spec["hurdle_candidates"]:
        penalty, inner = select_l2(frame, initial_end, hurdle, spec)
        policies = []
        for begin, end in inner_bounds(frame.start, initial_end):
            model = fit(frame, sample_indices(frame, frame.start, begin), hurdle, penalty, begin, spec)
            idx = np.flatnonzero((frame.times >= begin) & (frame.times < end) & frame.eligible)
            policy, _, _ = paper(frame, idx, predict(model, frame.x[idx]), begin, end, spec)
            policies.append(policy)
        acceptable = (sum(p["completed_trades"] for p in policies) >= spec["minimum_selection_trades"]
            and all(p["risk_complete"] and p["maximum_drawdown_observed"] <= spec["maximum_selection_drawdown"] for p in policies))
        score = float(np.mean([p["mean_daily_log_return"] for p in policies])) if acceptable else None
        reports.append(dict(hurdle=hurdle, selected_l2_lambda=penalty, eligible_for_selection=acceptable,
                            selection_score=score, policies=policies, inner_regularization=inner))
    acceptable = [r for r in reports if r["eligible_for_selection"]]
    winner = max(acceptable, key=lambda r:(r["selection_score"], -r["hurdle"])) if acceptable else None
    hurdle = winner["hurdle"] if winner else spec["fallback_hurdle"]
    return hurdle, dict(selected_hurdle=hurdle, economically_supported_hurdle=bool(winner),
        fallback_used=not bool(winner), selection_end=iso(initial_end), candidates=reports,
        warning="Selection scores are tuning evidence. Passing constraints does not establish a profitable edge.")


def score(frame, indices, model):
    y = (frame.future_return[indices] > model["hurdle"]).astype(int)
    p = predict(model, frame.x[indices])
    baseline = np.full(len(indices), model["training_prevalence"])
    return dict(model=metrics(y, p), training_prevalence_baseline=metrics(y, baseline)), p, baseline


def block_uncertainty(times, y, p, baseline, spec):
    """Paired calendar-block bootstrap; empty hours are not compressed away."""
    block_ids = (times - times[0]) // (spec["uncertainty_block_hours"] * HOUR)
    blocks = [np.flatnonzero(block_ids == i) for i in np.unique(block_ids)]
    if len(blocks) < 2:
        return dict(available=False, reason="Fewer than two calendar blocks")
    cp, cb = np.clip(p, 1e-15, 1 - 1e-15), np.clip(baseline, 1e-15, 1 - 1e-15)
    loss_delta = -y * np.log(cp) - (1-y) * np.log1p(-cp) + y * np.log(cb) + (1-y) * np.log1p(-cb)
    brier_delta = (p-y)**2 - (baseline-y)**2
    sums = np.array([[loss_delta[idx].sum(), brier_delta[idx].sum(), len(idx)] for idx in blocks])
    rng = np.random.default_rng(spec["random_seed"])
    draws = []
    for _ in range(spec["bootstrap_replicates"]):
        total = sums[rng.integers(0, len(blocks), len(blocks))].sum(axis=0)
        draws.append(total[:2] / total[2])
    draws = np.asarray(draws)
    return dict(available=True, calendar_blocks=len(blocks), block_hours=spec["uncertainty_block_hours"],
        replicates=spec["bootstrap_replicates"], interpretation="Model minus prevalence baseline; negative is better. Approximate dependence-aware intervals, not independent hourly trials.",
        log_loss_difference_95pct=np.quantile(draws[:,0], [.025,.975]).tolist(),
        brier_difference_95pct=np.quantile(draws[:,1], [.025,.975]).tolist())


def readiness(frame, spec):
    end = timestamp(spec["initial_development_end"])
    counts = []
    for begin, stop in inner_bounds(frame.start, end):
        counts.append(dict(training_end=iso(begin), validation_end=iso(stop),
            training_rows=len(sample_indices(frame, frame.start, begin)),
            validation_rows=len(sample_indices(frame, begin, stop))))
    years = Counter(iso(t)[:4] for t in frame.times[frame.eligible])
    initial_ready = all(f["training_rows"] > 0 and f["validation_rows"] > 0 for f in counts)
    return dict(calendar_development_hours=len(frame.x), feature_eligible_hours=int(frame.eligible.sum()),
        labeled_development_rows=len(sample_indices(frame, frame.start, frame.cutoff)),
        feature_eligible_by_year=dict(years), exclusion_counts=dict(Counter(r["reason"] for r in frame.exclusions)),
        initial_selection_folds=counts, initial_selection_ready=initial_ready,
        readiness_note="Nonempty folds only establish technical feasibility, not sufficient independent evidence." if initial_ready else
            "At least one frozen initial selection fold has no training or validation rows. Cannot run the specified selection protocol; no quality rule or split was changed.",
        reserved_oos_start=spec["development_end_exclusive"],
        oos_prices_parsed=False, incident_data_read=False, prior_inspection_disclosure=DISCLOSURE)


def provenance_paths(spec):
    files = [CONFIG, "NEWMODELS.MD", "scripts/train_xmr_hourly_baseline.py",
            "tests/test_xmr_hourly_baseline.py", "docs/HOURLY_PRICE_BASELINE.md", "requirements-analysis.txt",
            spec["xmr_path"], spec["btc_path"]]
    files.extend(spec[k] for k in ("price_review_path", "xmr_coverage_path", "btc_coverage_path",
                 "xmr_validation_path", "btc_validation_path") if k in spec)
    return files


def freeze(spec, root=ROOT):
    validate_spec(spec)
    verify_price_sources(spec, root)
    excluded_review_prices(spec, root)
    path = root / OUT / "FROZEN.json"
    if path.exists():
        return verify(spec, root)
    lock = dict(study_id=spec["study_id"], frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        config=spec, features=FEATURES, incident_data_read=False, reserved_period_evaluation_allowed=False,
        prior_inspection_disclosure=DISCLOSURE,
        implementation_choices=["Price-only features 1-5; standalone baseline has no incident-coverage gate.",
            "Combined converted XMR/USD prices; five-minute freshness unchanged.",
            "Unresolved flagged closes withheld according to pre-run source review.",
            "Float64 Newton optimization of the specified L2 objective.",
            "Paper fills delayed one hour; holding period starts at fill. Forecast labels keep the specified close clock.",
            "Missing intermediate portfolio marks make economic hurdle selection ineligible."],
        input_sha256={p:digest(root / p) for p in provenance_paths(spec)})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(lock))
    return lock


def verify(spec, root=ROOT):
    lock = json.loads((root / OUT / "FROZEN.json").read_text())
    if lock["config"] != spec:
        raise ValueError("Configuration changed after freeze")
    for path, expected in lock["input_sha256"].items():
        if digest(root / path) != expected:
            raise ValueError("Frozen input changed: " + path)
    return lock


def run(spec, root=ROOT, check_reproduction=False):
    verify(spec, root)
    folder = root / OUT / "results"
    if not check_reproduction and folder.exists() and any(folder.iterdir()):
        raise ValueError("Refusing to overwrite existing results")
    frame = load_frame(spec, root)
    if not readiness(frame, spec)["initial_selection_ready"]:
        raise ValueError("Frozen initial selection has an empty training/validation block. Run 'check' for counts; a documented pre-run specification revision is required.")
    initial_end = timestamp(spec["initial_development_end"])
    hurdle, selection = select_hurdle(frame, initial_end, spec)
    # Persist target/policy choice BEFORE any outer score is computed.
    selection_bytes = json_bytes(dict(selection=selection, policy=spec, feature_names=FEATURES))
    selected_path = root / OUT / "SELECTED.json"
    if selected_path.exists():
        if selected_path.read_bytes() != selection_bytes:
            raise ValueError("Previously frozen hurdle/policy differs")
    elif not check_reproduction:
        selected_path.write_bytes(selection_bytes)
    else:
        raise ValueError("Missing pre-outer selection freeze")
    outputs, reports, prediction_rows, uncertainty_parts = {}, [], [], []
    begin = initial_end
    for number, stop_string in enumerate(spec["outer_ends"], 1):
        end = timestamp(stop_string)
        penalty, inner = select_l2(frame, begin, hurdle, spec)
        model = fit(frame, sample_indices(frame, frame.start, begin), hurdle, penalty, begin, spec)
        validation = sample_indices(frame, begin, end)
        report, probabilities, baseline = score(frame, validation, model)
        y = (frame.future_return[validation] > hurdle).astype(int)
        uncertainty_parts.append((frame.times[validation], y, probabilities, baseline))
        for i, p, b in zip(validation, probabilities, baseline):
            prediction_rows.append(dict(fold=number, decision_time=iso(frame.times[i]),
                target_end=iso(frame.times[i] + 120 * HOUR), gross_return=float(frame.future_return[i]),
                target=int(frame.future_return[i] > hurdle), probability=float(p), prevalence_baseline=float(b)))
        trading = np.flatnonzero((frame.times >= begin) & (frame.times < end) & frame.eligible)
        trading_p = predict(model, frame.x[trading])
        policy, trades, curve = paper(frame, trading, trading_p, begin, end, spec)
        stress, _, _ = paper(frame, trading, trading_p, begin, end, spec, cost=2*spec["round_trip_cost"])
        buy_hold, _, buy_curve = paper(frame, np.array([], dtype=int), np.array([]), begin, end, spec, buy_hold=True)
        cash = dict(net_return=0.0, maximum_drawdown=0.0, volatility=0.0, sharpe=None)
        reports.append(dict(fold=number, start=iso(begin), end=iso(end), selected_l2=penalty,
            training_rows=model["training_rows"], classification=report, paper_policy=policy,
            double_cost_policy=stress, buy_and_hold=buy_hold, cash_benchmark=cash))
        outputs[f"models/fold_{number}.json"] = json_bytes(model)
        outputs[f"inner/fold_{number}.json"] = json_bytes(inner)
        outputs[f"paper/fold_{number}_trades.json"] = json_bytes(trades)
        outputs[f"paper/fold_{number}_equity.json"] = json_bytes(curve)
        outputs[f"paper/fold_{number}_buy_hold_equity.json"] = json_bytes(buy_curve)
        begin = end
    times, y, p, b = (np.concatenate(parts) for parts in zip(*uncertainty_parts))
    final_penalty, final_inner = select_l2(frame, frame.cutoff, hurdle, spec)
    final_indices = sample_indices(frame, frame.start, frame.cutoff)
    final = fit(frame, final_indices, hurdle, final_penalty, frame.cutoff, spec)
    in_sample, _, _ = score(frame, final_indices, final)
    summary = dict(study_id=spec["study_id"], selected_hurdle=hurdle,
        economically_supported_hurdle=selection["economically_supported_hurdle"], readiness=readiness(frame, spec),
        outer_folds=reports, pooled_outer=dict(model=metrics(y,p), training_prevalence_baseline=metrics(y,b)),
        uncertainty=block_uncertainty(times,y,p,b,spec), final_training_in_sample=in_sample,
        final_l2=final_penalty, heldout_outcomes_evaluated=False, incident_hypothesis_tested=False,
        independent_hourly_trials=False, prior_inspection_disclosure=DISCLOSURE,
        comparison_warning="Future incident models must use the same eligible comparison rows and frozen hurdle; this unrestricted baseline alone does not test incident value.")
    lines = ["# Hourly price-only baseline", "", DISCLOSURE, "",
        f"Frozen hurdle: {hurdle:.0%}. Economically supported selection: {selection['economically_supported_hurdle']}.",
        "No incident data used. Final 20% excluded. Outer scores never select features, hurdle or policy.", "",
        "| Fold | Rows | Log loss / baseline | Brier / baseline | AUC | Accuracy |",
        "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for r in reports:
        m, baseline = r["classification"]["model"], r["classification"]["training_prevalence_baseline"]
        auc = "undefined" if m["auc"] is None else f"{m['auc']:.4f}"
        lines.append(f"| {r['fold']} | {m['rows']} | {m['log_loss']:.4f} / {baseline['log_loss']:.4f} | {m['brier']:.4f} / {baseline['brier']:.4f} | {auc} | {m['accuracy']:.2%} |")
    lines += ["", "See summary.json for calibration, dependent-label uncertainty, economic results, cost stress and benchmarks.",
        "Portfolio marks missing from the source remain unknown; incomplete risk histories cannot support hurdle selection.",
        "Forecast labels use completed-close returns; paper fills occur one hour later. These are separate clocks.", ""]
    outputs.update({"summary.json":json_bytes(summary), "RESULTS.md":"\n".join(lines).encode(),
        "hurdle_selection.json":json_bytes(selection), "models/final_development.json":json_bytes(final),
        "inner/final.json":json_bytes(final_inner),
        "outer_predictions.csv":csv_bytes(prediction_rows, list(prediction_rows[0])),
        "exclusions.csv":csv_bytes(frame.exclusions, ["decision_time", "reason"])})
    # A complete input/target table supports later identical-row comparisons.
    metadata = {}
    with (root / spec["xmr_path"]).open(newline="") as handle:
        for row in csv.DictReader(handle):
            t = int(row["timestamp_unix"])
            if t >= frame.cutoff:
                break
            metadata[t+HOUR] = {k:row.get(k, "") for k in ("close_usd_source", "close_usd_minute_utc",
                "close_age_seconds", "close_uses_usd_proxy", "close_source_changed_from_prior_hour", "needs_price_review")}
    cohort = [dict(decision_time=iso(frame.times[i]), target_end=iso(frame.times[i]+120*HOUR),
                   **dict(zip(FEATURES, frame.x[i].tolist())), gross_return=float(frame.future_return[i]),
                   target=int(frame.future_return[i] > hurdle), **metadata.get(int(frame.times[i]), {}))
              for i in final_indices]
    outputs["cohort.csv"] = csv_bytes(cohort, list(cohort[0]))
    calibration = [dict(fold=r["fold"], **point) for r in reports for point in r["classification"]["model"]["calibration_bins"]]
    calibration += [dict(fold="pooled", **point) for point in summary["pooled_outer"]["model"]["calibration_bins"]]
    outputs["calibration_curve.csv"] = csv_bytes(calibration, ["fold", "lower", "upper", "rows", "mean_probability", "observed_frequency"])
    histogram = summary["pooled_outer"]["model"]["probability_histogram"]
    outputs["probability_distribution.csv"] = csv_bytes([dict(lower=histogram["edges"][i],
        upper=histogram["edges"][i+1], rows=count) for i,count in enumerate(histogram["counts"])], ["lower", "upper", "rows"])
    outputs["FINAL_FROZEN.json"] = json_bytes(dict(study_id=spec["study_id"],
        pre_run_freeze_sha256=digest(root / OUT / "FROZEN.json"), selected_policy_sha256=digest(selected_path),
        fitted_model_sha256=hashlib.sha256(outputs["models/final_development.json"]).hexdigest(),
        selected_hurdle=hurdle, selected_l2=final_penalty, feature_names=FEATURES,
        training_end_exclusive=iso(frame.cutoff), reserved_oos_evaluated=False,
        model_and_scaler_fixed=True, policy_fixed=True, prior_inspection_disclosure=DISCLOSURE))
    verify(spec, root)
    if check_reproduction:
        manifest = json.loads((folder / "RUN.json").read_text())
        if (manifest["freeze_sha256"] != digest(root / OUT / "FROZEN.json")
                or manifest["selected_sha256"] != digest(selected_path)
                or set(manifest["output_sha256"]) != set(outputs)):
            raise ValueError("Run manifest mismatch")
        for path, data in outputs.items():
            if ((folder / path).read_bytes() != data
                    or digest(folder / path) != manifest["output_sha256"][path]):
                raise ValueError("Reproduction mismatch: " + path)
    else:
        for path, data in outputs.items():
            destination = folder / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        manifest = dict(freeze_sha256=digest(root / OUT / "FROZEN.json"),
            selected_sha256=digest(selected_path), runtime=dict(python=platform.python_version(), numpy=np.__version__),
            heldout_outcomes_evaluated=False, output_sha256={p:digest(folder / p) for p in outputs})
        (folder / "RUN.json").write_bytes(json_bytes(manifest))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    sub.add_parser("check")
    sub.add_parser("freeze")
    p = sub.add_parser("run"); p.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    spec = json.loads((ROOT / CONFIG).read_text())
    try:
        if args.command == "prepare":
            ledger = prepare_review(spec)
            result = {k:ledger[k] for k in ("disposition_counts", "source_verification", "source_switch_review", "no_model_outcomes_used")}
        elif args.command == "check":
            result = readiness(load_frame(spec), spec)
        elif args.command == "freeze":
            result = freeze(spec)
        else:
            report = run(spec, check_reproduction=args.verify)
            result = {k:report[k] for k in ("selected_hurdle", "economically_supported_hurdle", "pooled_outer", "heldout_outcomes_evaluated")}
    except (ValueError, FileNotFoundError) as error:
        parser.exit(2, f"Cannot complete {args.command}: {error}\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
