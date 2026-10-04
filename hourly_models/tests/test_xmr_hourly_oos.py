"""Reserved evaluation: fixed scalers, shared rows, boundary clocks and no fit."""
import copy
import csv
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import numpy as np
import evaluate_xmr_hourly_oos as evaluator
import train_xmr_hourly_incident as core


class FrozenOOSTests(unittest.TestCase):
    def setUp(self):
        self.begin = core.timestamp("2020-01-10T00:00:00Z")
        self.end = self.begin + 400 * core.HOUR
        self.spec = dict(core.DEFAULT_SPEC, development_end_exclusive=core.iso(self.begin),
                         history_end_exclusive=core.iso(self.end))

    def models(self):
        return {name: dict(model_name=name, feature_names=core.FEATURES[:size],
            scaler_mean=[1.] * size, scaler_scale=[2.] * size,
            coefficients=[.2] * size, intercept=.8, training_prevalence=.35,
            training_end_exclusive=self.spec["development_end_exclusive"], hurdle=.03,
            l2_lambda=.01) for name, size in core.MODELS.items()}

    def frame(self):
        start = self.begin - 169 * core.HOUR
        n = 569
        audit = [dict(selected_incident_id="", active_incident_ids=[]) for _ in range(n)]
        return core.Frame(start, self.end, np.full(n+1, 100.), np.full(n+1, 100.),
            np.zeros((n, 8)), np.ones(n, dtype=bool), np.full(n, .04), audit, [])

    def test_complete_targets_use_timestamp_boundary_and_shared_signals(self):
        frame = self.frame()
        frame.outcome_eligible[180] = False
        frame.x[181, 0] = np.nan
        labeled = evaluator.oos_indices(frame, self.spec)
        signals = evaluator.oos_indices(frame, self.spec, labeled=False)
        self.assertEqual(labeled[0], 169)
        self.assertIn(449, labeled)  # target ends exactly at the reserve end
        self.assertNotIn(450, labeled)
        self.assertNotIn(180, labeled)
        self.assertIn(180, signals)  # a future endpoint cannot gate entry
        self.assertNotIn(181, signals)
        self.assertEqual(signals[-1], 568)

    def test_frozen_scaler_transform_is_used_without_mutation(self):
        frozen = self.models()["market"]
        original = copy.deepcopy(frozen)
        x = np.array([[3.] * 8, [-1.] * 8])
        actual = core.predict(frozen, x)
        np.testing.assert_allclose(actual, [1 / (1 + math.exp(-1.8)), 1 / (1 + math.exp(.2))])
        self.assertEqual(frozen, original)

    def test_model_identity_scaler_and_hurdle_are_validated(self):
        frozen = dict(policy=core.DEFAULT_SPEC, selected_hurdle=.03,
                      incident_mode="retrospective_catalog_date", models=self.models())
        for m in frozen["models"].values():
            m["training_end_exclusive"] = core.DEFAULT_SPEC["development_end_exclusive"]
        evaluator.validate_models(frozen)
        for mutation in ("scaler", "features", "boundary", "hurdle"):
            altered = copy.deepcopy(frozen)
            m = altered["models"]["market"]
            if mutation == "scaler": m["scaler_scale"][0] = 0
            if mutation == "features": m["feature_names"][0] = "wrong"
            if mutation == "boundary": m["training_end_exclusive"] = "2025-01-01T00:00:00Z"
            if mutation == "hurdle": m["hurdle"] = .04
            with self.assertRaises(ValueError):
                evaluator.validate_models(altered)

    def write_prices(self, root, spec, flag_index=None):
        start = self.begin - 169 * core.HOUR
        fields = ["timestamp_unix", "timestamp_utc", "close_usd", "close_age_seconds", "needs_price_review"]
        for asset in ("xmr", "btc"):
            path = root / spec[asset + "_path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fields); writer.writeheader()
                for i in range(570):
                    at = start + i * core.HOUR
                    writer.writerow(dict(timestamp_unix=at, timestamp_utc=core.iso(at),
                        close_usd="OUTSIDE_POISON" if at == self.end else 100*math.exp(i*.0001),
                        close_age_seconds="OUTSIDE_POISON" if at == self.end else 60,
                        needs_price_review="1" if i == flag_index and asset == "xmr" else "0"))
        catalog = root / spec["incident_catalog_path"]
        catalog.parent.mkdir(parents=True, exist_ok=True)
        catalog.write_text("incident_id,incident_date,reported_loss_usd\na,2020-01-09,10000000\n")

    def test_backwards_history_completed_closes_incidents_and_outside_poison(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = dict(self.spec, expected_catalog_rows=1)
            self.write_prices(root, spec)
            frame = evaluator.load_oos_frame(root, dict(policy=spec), [], outcomes=True)
            labeled = evaluator.oos_indices(frame, spec)
            self.assertEqual(labeled[0], 169)
            self.assertEqual(labeled[-1], 449)
            self.assertAlmostEqual(frame.x[169, 0], 24*.0001)
            self.assertAlmostEqual(frame.x[169, 1], 144*.0001)
            self.assertAlmostEqual(frame.x[169, 4], math.sqrt(24)*.0001)
            self.assertAlmostEqual(frame.future_return[169], math.exp(120*.0001)-1)
            self.assertEqual(frame.x[169, 5:].tolist(), [1., math.log1p(10), 0.])
            self.assertEqual(frame.x[192, 7], 23)
            self.assertEqual(frame.x[193, 5:].tolist(), [0., 0., 0.])

    def test_new_flag_disposition_is_frozen_unresolved_without_reading_price(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = dict(self.spec, expected_catalog_rows=1)
            self.write_prices(root, spec, flag_index=170)
            path = root / spec["price_review_path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(core.json_bytes(dict(xmr_source_sha256=core.digest(root / spec["xmr_path"]),
                development_end_exclusive=spec["development_end_exclusive"], rows=[])))
            rows = evaluator.price_dispositions(root, spec, self.begin - 169*core.HOUR, self.end)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["disposition"], "unresolved")
            frame = evaluator.load_oos_frame(root, dict(policy=spec), rows, outcomes=False)
            self.assertTrue(np.isnan(frame.xmr[171]))
            self.assertFalse(frame.eligible[171])
            self.assertFalse(np.isfinite(frame.future_return).any())
            outputs = evaluator.preparation_outputs(frame, spec)
            header = outputs["hourly_inputs.csv"].decode().splitlines()[0]
            self.assertNotIn("gross_return", header)
            self.assertNotIn(",target,", header)
            self.assertIn("target_crosses_oos_boundary", outputs["exclusions.csv"].decode())

    def test_run_has_no_fit_or_selection_future_gate_and_is_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / evaluator.OUT
            folder.mkdir(parents=True)
            frozen = dict(policy=self.spec, models=self.models(), prior_inspection_disclosure="prior inspection",
                          amendment_timing_disclosure="amended after development scores")
            record = dict(price_dispositions=[])
            (root / evaluator.FINAL).parent.mkdir(parents=True)
            (root / evaluator.FINAL).write_bytes(core.json_bytes(frozen))
            for name in ("EVALUATION_FROZEN.json", "PREPARATION.json", "eligibility.json"):
                (folder / name).write_text("{}\n")
            frame = self.frame()
            # All three model probabilities exceed .60. The first signal has
            # a missing classification endpoint but an executable next-hour trade.
            frame.outcome_eligible[169] = False
            frame.x[:, :] = 3.
            before = copy.deepcopy(frozen)
            with patch.object(evaluator, "verify_preparation", return_value=(frozen, record)), \
                 patch.object(evaluator, "load_oos_frame", return_value=frame), \
                 patch.object(core, "fit", side_effect=AssertionError("No fit allowed")), \
                 patch.object(core, "select_l2", side_effect=AssertionError("No tuning allowed")):
                result = evaluator.run(root)
                self.assertEqual(result["classification"]["market"]["overall"]["rows"], 280)
                self.assertEqual(result["feature_eligible_policy_signals"], 400)
                self.assertFalse(result["fitting_performed"])
                for name in core.MODELS:
                    policy = json.loads((folder / "results/paper" / (name + ".json")).read_text())
                    self.assertEqual(policy["trades"][0]["signal_time"], core.iso(self.begin))
                    self.assertEqual(policy["trades"][0]["entry_time"], core.iso(self.begin+core.HOUR))
                    self.assertEqual(policy["trades"][0]["exit_time"], core.iso(self.begin+121*core.HOUR))
                self.assertEqual(evaluator.run(root, verify_only=True), result)
                with self.assertRaisesRegex(ValueError, "already scored"):
                    evaluator.run(root)
            self.assertEqual(frozen, before)

    def test_hash_change_fails_before_scoring(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root / "frozen.json"
            path.write_text("before")
            hashes = {"frozen.json": core.digest(path)}
            evaluator.checked_hashes(root, hashes)
            path.write_text("after")
            with self.assertRaisesRegex(ValueError, "Frozen input changed"):
                evaluator.checked_hashes(root, hashes)


if __name__ == "__main__":
    unittest.main()
