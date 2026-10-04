"""Evaluate the reserved 20% with three frozen models; never fit or tune.

prepare pins models, inputs, code and price dispositions before outcome scoring.
run scores once in a separate folder. verify reproduces outputs without writes.
The development trainers and their historical manifests remain unchanged.
"""
import argparse
import csv
import hashlib
import json
import platform
from collections import Counter
from pathlib import Path

import numpy as np
import train_xmr_hourly_incident as core

ROOT = Path(__file__).resolve().parents[1]
FINAL = "docs/models/xmr_hourly_incident_catalog_v2/results/FINAL_FROZEN.json"
OUT = "docs/models/xmr_hourly_incident_catalog_v2/oos_v1"
LOOKBACK_HOURS = 169  # Include the bar ending at the earliest 168-hour boundary.


def read_json(path):
    return json.loads(Path(path).read_text())


def checked_hashes(root, hashes):
    for name, expected in hashes.items():
        if core.digest(root / name) != expected:
            raise ValueError("Frozen input changed: " + name)


def validate_models(frozen):
    spec = frozen["policy"]
    core.validate_spec(spec)  # Keep the training runner's OOS prohibition intact.
    if frozen["selected_hurdle"] != .03 or frozen["incident_mode"] != "retrospective_catalog_date":
        raise ValueError("The frozen 3% catalog-date experiment is required")
    if set(frozen["models"]) != set(core.MODELS):
        raise ValueError("Exactly the three final models are required")
    for name, size in core.MODELS.items():
        model = frozen["models"][name]
        if (model["model_name"] != name or model["feature_names"] != core.FEATURES[:size]
                or model["hurdle"] != .03
                or model["training_end_exclusive"] != spec["development_end_exclusive"]):
            raise ValueError("Final model identity, target or training boundary mismatch: " + name)
        for key in ("scaler_mean", "scaler_scale", "coefficients"):
            values = np.asarray(model[key], dtype=float)
            if values.shape != (size,) or not np.isfinite(values).all():
                raise ValueError("Malformed frozen model: " + name + "/" + key)
        if (np.any(np.asarray(model["scaler_scale"]) <= 0)
                or not np.isfinite(model["intercept"])
                or not 0 < model["training_prevalence"] < 1):
            raise ValueError("Invalid frozen scaler, intercept or prevalence: " + name)
    if len({m["training_prevalence"] for m in frozen["models"].values()}) != 1:
        raise ValueError("Frozen models do not share a training population")


def training_inputs(root):
    frozen = read_json(root / FINAL)
    validate_models(frozen)
    checked_hashes(root, frozen["source_code_hashes"])
    result_dir = (root / FINAL).parent
    run = read_json(result_dir / "RUN.json")
    dependencies = dict(frozen["source_code_hashes"])
    for filename in ("FINAL_FROZEN.json", *["models/final_" + n + ".json" for n in core.MODELS]):
        path = result_dir / filename
        if core.digest(path) != run["output_sha256"][filename]:
            raise ValueError("Archived final training artifact changed: " + filename)
        dependencies[str(path.relative_to(root))] = core.digest(path)
        if filename.startswith("models/"):
            name = filename.removeprefix("models/final_").removesuffix(".json")
            if read_json(path) != frozen["models"][name]:
                raise ValueError("Embedded and separately saved final model differ: " + name)
    study = result_dir.parent
    for filename, key in (("PRE_RUN.json", "pre_run_sha256"), ("SELECTED.json", "selected_sha256")):
        path = study / filename
        if core.digest(path) != frozen[key]:
            raise ValueError("Final training provenance mismatch: " + filename)
        dependencies[str(path.relative_to(root))] = core.digest(path)
    dependencies[str((result_dir / "RUN.json").relative_to(root))] = core.digest(result_dir / "RUN.json")
    for filename in ("scripts/evaluate_xmr_hourly_oos.py", "tests/test_xmr_hourly_oos.py", "docs/HOURLY_OOS_EVALUATION.md"):
        dependencies[filename] = core.digest(root / filename)
    return frozen, dependencies


def price_dispositions(root, spec, begin, end):
    """Use source flags only; no numeric close or future return influences review."""
    ledger = read_json(root / spec["price_review_path"])
    if (ledger["xmr_source_sha256"] != core.digest(root / spec["xmr_path"])
            or ledger["development_end_exclusive"] != spec["development_end_exclusive"]):
        raise ValueError("The frozen development price ledger does not match this snapshot")
    previous = {core.timestamp(row["bar_start"]): row for row in ledger["rows"]}
    if (len(previous) != len(ledger["rows"])
            or any(r["disposition"] not in ("accepted", "invalid", "unresolved") or not r["reason"] for r in previous.values())):
        raise ValueError("Malformed archived price-review ledger")
    chosen = {}
    with (root / spec["xmr_path"]).open(newline="") as handle:
        for row in csv.DictReader(handle):
            at = int(row["timestamp_unix"])
            if begin <= at < end and row.get("needs_price_review") == "1":
                chosen[at] = dict(previous[at]) if at in previous else dict(
                    bar_start=core.iso(at), disposition="unresolved", action="exclude_required_close",
                    reason="Flagged source close has no frozen acceptance; apply the unchanged unresolved-price exclusion without outcome-based review.")
    return [chosen[at] for at in sorted(chosen)]


def load_oos_frame(root, frozen, dispositions, outcomes=False):
    spec = frozen["policy"]
    begin, end = map(core.timestamp, (spec["development_end_exclusive"], spec["history_end_exclusive"]))
    start = begin - LOOKBACK_HOURS * core.HOUR
    audit = []
    xmr, qx = core.read_closes(root / spec["xmr_path"], start, end,
        spec["maximum_close_age_seconds"], audit=audit,
        dispositions={core.timestamp(row["bar_start"]): row for row in dispositions})
    btc, qb = core.read_closes(root / spec["btc_path"], start, end, spec["maximum_close_age_seconds"])
    with (root / spec["incident_catalog_path"]).open(newline="") as handle:
        catalog = list(csv.DictReader(handle))
    if len(catalog) != spec["expected_catalog_rows"]:
        raise ValueError("Frozen catalog row count changed")
    windows, catalog_audit = core.catalog_windows(catalog, spec)
    frame = core.build_frame(xmr, btc, start, end, windows, spec, outcomes,
        quality={"xmr": qx, "btc": qb})
    frame.price_audit, frame.catalog_audit = audit, catalog_audit
    frame.exclusions = [dict(row, reason=row["reason"].replace("development_boundary", "oos_boundary"))
                        for row in frame.exclusions if core.timestamp(row["decision_time"]) >= begin]
    return frame


def oos_indices(frame, spec, labeled=True):
    begin, end = map(core.timestamp, (spec["development_end_exclusive"], spec["history_end_exclusive"]))
    if labeled:
        return core.sample_indices(frame, begin, end)
    # Future target/fill/exit validity must not gate paper-policy signals.
    return np.flatnonzero((frame.times >= begin) & (frame.times < end) & frame.eligible)


def preparation_outputs(frame, spec):
    indices = np.flatnonzero(frame.times >= core.timestamp(spec["development_end_exclusive"]))
    labeled = set(map(int, oos_indices(frame, spec)))
    rows = []
    for i in indices:
        context = frame.audit[i]
        rows.append(dict(decision_time=core.iso(frame.times[i]),
            target_end=core.iso(frame.times[i] + spec["horizon_hours"] * core.HOUR),
            feature_eligible=bool(frame.eligible[i]), classification_eligible=int(i) in labeled,
            **{name: float(value) if np.isfinite(value) else None for name, value in zip(core.FEATURES, frame.x[i])},
            selected_incident_id=context["selected_incident_id"],
            assumed_activation_utc=context["assumed_activation_utc"],
            assigned_incident_date=context["assigned_incident_date"],
            selected_catalog_loss_usd=context["selected_catalog_loss_usd"],
            active_incident_ids=json.dumps(context["active_incident_ids"]),
            verified_information_available=False))
    report = dict(calendar_oos_hours=len(indices), common_feature_eligible_hours=len(oos_indices(frame, spec, False)),
        common_classification_rows=len(labeled), label_return_values_calculated=False,
        exclusion_counts=dict(Counter(row["reason"] for row in frame.exclusions)),
        price_quality_rules_changed=False, incident_mapping_changed=False,
        lookback_calendar_hours=LOOKBACK_HOURS, earlier_prices_used_only_for_backward_features=True)
    return {"hourly_inputs.csv": core.csv_bytes(rows, list(rows[0])),
        "exclusions.csv": core.csv_bytes(frame.exclusions, ["decision_time", "reason", "selected_incident_id", "unresolved_incident_ids", "missing_required_sources"]),
        "price_quality.csv": core.csv_bytes(frame.price_audit, list(frame.price_audit[0])),
        "eligibility.json": core.json_bytes(report)}


def prepare(root=ROOT):
    frozen, hashes = training_inputs(root)
    spec = frozen["policy"]
    begin, end = map(core.timestamp, (spec["development_end_exclusive"], spec["history_end_exclusive"]))
    folder = root / OUT
    if folder.exists():
        raise ValueError("OOS preparation already exists; use run or verify without overwriting")
    dispositions = price_dispositions(root, spec, begin - LOOKBACK_HOURS * core.HOUR, end)
    folder.mkdir(parents=True)
    record = dict(final_frozen_path=FINAL, input_sha256=hashes,
        evaluation_start=core.iso(begin), evaluation_end_exclusive=core.iso(end),
        selected_hurdle=.03, fitting_allowed=False, scaler_estimation_allowed=False,
        tuning_allowed=False, paper_future_target_eligibility_gate=False,
        complete_classification_targets_required=True,
        price_dispositions=dispositions, previously_unreviewed_flags="unresolved; exclude all required uses",
        training_runner_reserved_evaluation_flag_unchanged=spec["reserved_period_evaluation_allowed"],
        prior_inspection_disclosure=frozen["prior_inspection_disclosure"],
        amendment_timing_disclosure=frozen["amendment_timing_disclosure"],
        protocol_frozen_before_oos_outcome_scoring=True, training_artifacts_will_be_overwritten=False)
    (folder / "EVALUATION_FROZEN.json").write_bytes(core.json_bytes(record))
    frame = load_oos_frame(root, frozen, dispositions, outcomes=False)
    outputs = preparation_outputs(frame, spec)
    for name, data in outputs.items():
        (folder / name).write_bytes(data)
    (folder / "PREPARATION.json").write_bytes(core.json_bytes(dict(
        evaluation_freeze_sha256=core.digest(folder / "EVALUATION_FROZEN.json"),
        output_sha256={name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()})))
    return read_json(folder / "eligibility.json")


def verify_preparation(root):
    folder = root / OUT
    record, preparation = read_json(folder / "EVALUATION_FROZEN.json"), read_json(folder / "PREPARATION.json")
    if core.digest(folder / "EVALUATION_FROZEN.json") != preparation["evaluation_freeze_sha256"]:
        raise ValueError("OOS pre-score freeze changed")
    checked_hashes(root, record["input_sha256"])
    checked_hashes(folder, preparation["output_sha256"])
    frozen = read_json(root / record["final_frozen_path"])
    validate_models(frozen)
    return frozen, record


def results_markdown(summary):
    lines = ["# Frozen-model reserved-20% evaluation", "",
        f"Period: {summary['start']} through {summary['end_exclusive']} (exclusive).",
        "Target: gross XMR/USD return strictly above 3% over 120 hours. No fitting, scaler estimation or tuning.", "",
        summary["prior_inspection_disclosure"], "", summary["amendment_timing_disclosure"], "",
        "| Subset | Model | Rows | Log loss | Brier | AUC | Accuracy |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for subset in ("overall", "active_incident", "ordinary"):
        for name, group in summary["classification"].items():
            m = group[subset]
            if not m["available"]:
                lines.append(f"| {subset} | {name} | 0 | unavailable | unavailable | unavailable | unavailable |")
                continue
            auc = "unavailable" if m["auc"] is None else f"{m['auc']:.6f}"
            lines.append(f"| {subset} | {name} | {m['rows']} | {m['log_loss']:.6f} | {m['brier']:.6f} | {auc} | {m['accuracy']:.2%} |")
    def pct(value):
        return "unavailable" if value is None else f"{value:.2%}"
    lines += ["", "| Paper policy | Completed | Unresolved | Unfilled | Net return | Max drawdown | Time invested |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, p in summary["paper_policy"].items():
        lines.append(f"| {name} | {p['completed_trades']} | {p['unresolved_trades']} | {p['unfilled_orders']} | {pct(p['net_return'])} | {pct(p['maximum_drawdown'])} | {pct(p['time_invested'])} |")
    for name, p in summary["double_cost_stress"].items():
        lines.append(f"| {name} (4% cost) | {p['completed_trades']} | {p['unresolved_trades']} | {p['unfilled_orders']} | {pct(p['net_return'])} | {pct(p['maximum_drawdown'])} | {pct(p['time_invested'])} |")
    lines += ["", "The policy uses p >= 0.60, 10% equity per position, one long position, a one-hour delayed fill and 120 hours held from that fill; costs are subtracted once. Classification instead measures 120 hours from the decision close. Signals are not filtered by future target or exit validity.",
        "Buy-and-hold uses 100% initial XMR exposure and a next-hour entry, versus 10% per model trade. Unknown marks make drawdown unavailable; a missing scheduled exit remains unresolved. Cash returns zero.", "",
        f"{summary['classification']['market']['overall']['rows']} identical classification rows; {summary['classification']['market']['active_incident']['rows']} incident-active rows; {summary['classification']['market']['incidents']['distinct_incidents']} distinct active catalog groups.",
        "Probability distributions, calibration, 168-hour paired block intervals, all feature/price exclusions, policy signals and trade ledgers are saved alongside this report.", "",
        "Labels overlap 119/120 hourly intervals. Catalog dates and eventual loss estimates remain retrospective proxies. These reserved-model scores do not establish causal incident effects, verified live incident availability or executable cross-venue fills. Do not change settings in response to these scores.", ""]
    return "\n".join(lines).encode()


def run(root=ROOT, verify_only=False):
    frozen, record = verify_preparation(root)
    folder = root / OUT / "results"
    if folder.exists() and not verify_only:
        raise ValueError("OOS was already scored; use verify to reproduce without overwriting or tuning")
    if not folder.exists() and verify_only:
        raise ValueError("No completed OOS result exists to verify")
    spec = frozen["policy"]
    begin, end = map(core.timestamp, (spec["development_end_exclusive"], spec["history_end_exclusive"]))
    frame = load_oos_frame(root, frozen, record["price_dispositions"], outcomes=True)
    indices, signals = oos_indices(frame, spec), oos_indices(frame, spec, False)
    if not len(indices):
        raise ValueError("No eligible reserved classification rows under the frozen rules")
    y = (frame.future_return[indices] > .03).astype(int)
    probabilities = {name: core.predict(model, frame.x[indices]) for name, model in frozen["models"].items()}
    probabilities["prevalence"] = np.full(len(indices), frozen["models"]["market"]["training_prevalence"])
    comparisons = {name: core.score_groups(frame, indices, y, p) for name, p in probabilities.items()}
    outputs, policies, stress, signal_probabilities = {}, {}, {}, {}
    for name, model in frozen["models"].items():
        signal_probabilities[name] = core.predict(model, frame.x[signals])
        for doubled in (False, True):
            policy, trades, unresolved, curve = core.paper(frame, signals, signal_probabilities[name], begin, end,
                spec, cost=(2 if doubled else 1) * spec["round_trip_cost"])
            policy["mark_cost_convention"] = f"Reserve the full {policy['round_trip_cost']:.0%} round-trip cost against initial notional; deduct once on settlement."
            (stress if doubled else policies)[name] = policy
            suffix = "_double_cost" if doubled else ""
            outputs[f"paper/{name}{suffix}.json"] = core.json_bytes(dict(policy=policy,
                trades=trades, unresolved=unresolved, daily_equity=curve))
    buy, trades, unresolved, curve = core.paper(frame, np.array([], dtype=int), np.array([]), begin, end, spec, buy_hold=True)
    buy["exposure_disclosure"] = "100% initial XMR versus 10% per model trade; same next-hour entry and 2% additive cost."
    policies["buy_and_hold"] = buy
    policies["cash"] = dict(completed_trades=0, unresolved_trades=0, unfilled_orders=0,
        net_return=0.0, maximum_drawdown=0.0, time_invested=0.0, complete=True, risk_complete=True)
    outputs["paper/buy_and_hold.json"] = core.json_bytes(dict(policy=buy, trades=trades, unresolved=unresolved, daily_equity=curve))
    rows = [dict(decision_time=core.iso(frame.times[i]), target_end=core.iso(frame.times[i] + 120 * core.HOUR),
        gross_return=float(frame.future_return[i]), target=int(y[j]), incident_active=int(frame.x[i, 5]),
        selected_incident_id=frame.audit[i]["selected_incident_id"],
        **{name + "_probability": float(p[j]) for name, p in probabilities.items()}) for j, i in enumerate(indices)]
    signal_rows = [dict(decision_time=core.iso(frame.times[i]), incident_active=int(frame.x[i, 5]),
        classification_eligible=bool(frame.outcome_eligible[i] and frame.times[i] + 120 * core.HOUR <= end),
        **{name + "_probability": float(p[j]) for name, p in signal_probabilities.items()}) for j, i in enumerate(signals)]
    summary = dict(study_id="xmr_hourly_incident_catalog_v2_oos_v1", start=core.iso(begin), end_exclusive=core.iso(end),
        selected_hurdle=.03, classification=comparisons, paper_policy=policies, double_cost_stress=stress,
        uncertainty={name + "_minus_" + reference: core.block_uncertainty(frame.times[indices], y,
            probabilities[name], probabilities[reference], spec) for name, reference in
            (("market", "prevalence"), ("presence", "market"), ("full_incident", "market"))},
        eligibility=read_json(root / OUT / "eligibility.json"), feature_eligible_policy_signals=len(signals),
        identical_classification_row_membership=True, fitting_performed=False, scaler_estimation_performed=False,
        tuning_performed=False, reserved_outcomes_scored=True, archived_training_manifest_changed=False,
        model_final_l2={name: model["l2_lambda"] for name, model in frozen["models"].items()},
        prior_inspection_disclosure=frozen["prior_inspection_disclosure"],
        amendment_timing_disclosure=frozen["amendment_timing_disclosure"])
    outputs.update({"summary.json": core.json_bytes(summary), "RESULTS.md": results_markdown(summary),
        "predictions.csv": core.csv_bytes(rows, list(rows[0])),
        "policy_signals.csv": core.csv_bytes(signal_rows, list(signal_rows[0])),
        "calibration.svg": core.calibration_svg({name: group["overall"] for name, group in comparisons.items()})})
    verify_preparation(root)  # Recheck inputs and frozen artifacts before publishing outputs.
    manifest = dict(evaluation_freeze_sha256=core.digest(root / OUT / "EVALUATION_FROZEN.json"),
        preparation_sha256=core.digest(root / OUT / "PREPARATION.json"),
        final_frozen_sha256=core.digest(root / FINAL), reserved_outcomes_scored=True,
        runtime=dict(python=platform.python_version(), numpy=np.__version__),
        output_sha256={name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()})
    for name, data in outputs.items():
        path = folder / name
        if verify_only:
            if path.read_bytes() != data:
                raise ValueError("OOS reproduction mismatch: " + name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    if verify_only:
        if read_json(folder / "RUN.json") != manifest:
            raise ValueError("OOS run manifest mismatch")
    else:
        (folder / "RUN.json").write_bytes(core.json_bytes(manifest))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "verify"))
    args = parser.parse_args()
    result = prepare() if args.command == "prepare" else run(verify_only=args.command == "verify")
    if args.command == "prepare":
        print(json.dumps(result, indent=2))
    else:
        for name, group in result["classification"].items():
            m = group["overall"]
            print(f"{name}: rows={m['rows']} log_loss={m['log_loss']:.6f} brier={m['brier']:.6f} auc={m['auc']} accuracy={m['accuracy']:.6f}")
        print("Saved results: " + str(ROOT / OUT / "results/RESULTS.md"))


if __name__ == "__main__":
    main()
