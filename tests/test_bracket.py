"""Pure bounded-discovery tests; all simulation calls are mock callbacks."""
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ieee39ts.bracket import (DISCOVERY_DURATIONS_S, EXTENDED_FIELDS, SEED_DURATION_S,
    discover_bracket, extend_day2_results, identity_matches, write_extended_summary)
from ieee39ts.cct import search_cct
from ieee39ts.types import FaultResult


def outcome(duration, status="STABLE", **metadata):
    return {"clearing_duration_s": duration, "stability_status": status,
            "simulation_status": "COMPLETED" if status == "STABLE" else "ANGLE_CRITERION_STOP",
            **metadata}


def day2_row(bus, status="UNRESOLVED", reason="NO_UNSTABLE_ENDPOINT_IN_RANGE"):
    return {"fault_id": f"bus{bus:02d}", "fault_bus": bus, "search_status": status,
            "cct_reason": reason, "cct_estimate_s": .19140625 if status == "RESOLVED" else None,
            "stable_lower_s": .1875 if status == "RESOLVED" else SEED_DURATION_S,
            "unstable_upper_s": .1953125 if status == "RESOLVED" else None,
            "interval_width_s": .0078125 if status == "RESOLVED" else None,
            "failed_clearing_time_s": None, "trial_count": 7 if status == "RESOLVED" else 2,
            "cct_directory": f"bus{bus:02d}/cct"}


class BracketDiscoveryTests(unittest.TestCase):
    def test_stable_stable_unstable_calls_existing_binary_search(self):
        calls = []
        def trial(duration):
            calls.append(duration)
            return outcome(duration, "STABLE" if duration < .36 else "UNSTABLE")
        with patch("ieee39ts.bracket.search_cct", wraps=search_cct) as core:
            report = discover_bracket(trial, seed=outcome(SEED_DURATION_S))
        core.assert_called_once()
        self.assertEqual(calls[:3], [.25, .3125, .375])
        self.assertNotIn(.5, calls)
        self.assertEqual(report["search_status"], "RESOLVED")
        self.assertEqual((report["stable_lower_s"], report["unstable_upper_s"]), (.359375, .3671875))
        self.assertEqual(report["cct_estimate_s"], .36328125)
        self.assertEqual(report["binary_endpoint_reuses"], 2)
        self.assertEqual(calls.count(.3125), 1)
        self.assertEqual(calls.count(.375), 1)

    def test_stable_then_nonconvergent_stops_immediately(self):
        calls = []
        def trial(duration):
            calls.append(duration)
            return outcome(duration, "STABLE" if duration == .25 else "NON_CONVERGENT")
        report = discover_bracket(trial, seed=outcome(SEED_DURATION_S))
        self.assertEqual(calls, [.25, .3125])
        self.assertEqual(report["reason"], "NON_CONVERGENT_BRACKET_DISCOVERY")
        self.assertEqual(report["stable_lower_s"], .25)
        self.assertIsNone(report["unstable_upper_s"])
        self.assertIsNone(report["cct_estimate_s"])
        self.assertEqual(report["failed_clearing_time_s"], .3125)

    def test_half_second_stable_is_lower_bound_not_estimate(self):
        calls = []
        report = discover_bracket(lambda duration: (calls.append(duration) or outcome(duration)),
                                  seed=outcome(SEED_DURATION_S))
        self.assertEqual(calls, list(DISCOVERY_DURATIONS_S))
        self.assertEqual(report["reason"], "NO_UNSTABLE_ENDPOINT_WITHIN_0P5S")
        self.assertEqual(report["stable_lower_s"], .5)
        self.assertIsNone(report["unstable_upper_s"])
        self.assertIsNone(report["cct_estimate_s"])
        self.assertIn(">0.5 s", report["cct_range_statement"])

    def test_failure_is_not_an_unstable_endpoint(self):
        with patch("ieee39ts.bracket.search_cct") as core:
            report = discover_bracket(lambda duration: outcome(duration, "NON_CONVERGENT"),
                                      seed=outcome(SEED_DURATION_S))
        core.assert_not_called()
        self.assertEqual(report["stable_lower_s"], SEED_DURATION_S)
        self.assertIsNone(report["unstable_upper_s"])

    def test_invalid_quality_stops_and_preserves_reported_classification(self):
        original = FaultResult(outcome(.25, "UNSTABLE", tail_invalid=True,
                                      first_quality_failure_s=1.24, quality_failure_reasons=["INVALID_VOLTAGE_RANGE"]))
        calls = []
        report = discover_bracket(lambda duration: (calls.append(duration) or original),
                                  seed=outcome(SEED_DURATION_S))
        self.assertEqual(calls, [.25])
        self.assertIsNone(report["unstable_upper_s"])
        self.assertEqual(report["trials"][0]["reported_stability_status"], "UNSTABLE")
        self.assertEqual(report["trials"][0]["stability_status"], "NON_CONVERGENT")
        self.assertEqual(original.summary["stability_status"], "UNSTABLE")

    def test_existing_resolved_cases_are_not_run(self):
        rows = [day2_row(10, "RESOLVED", "VERIFIED_BRACKET_WITHIN_TOLERANCE"),
                day2_row(16, "RESOLVED", "VERIFIED_BRACKET_WITHIN_TOLERANCE")]
        def forbidden(bus, duration):
            self.fail("Resolved cases must never run TDS")
        report = extend_day2_results(rows, forbidden)
        self.assertEqual([r["extension_trials"] for r in report["results"]], [0, 0])
        self.assertEqual([r["cct_estimate_s"] for r in report["results"]], [.19140625, .19140625])

    def test_bus6_existing_failure_explicitly_skipped_and_retained(self):
        row = day2_row(6, reason="NON_CONVERGENT_MIDPOINT")
        row.update(stable_lower_s=.109375, unstable_upper_s=.1953125,
                   interval_width_s=.0859375, failed_clearing_time_s=.1484375, trial_count=4)
        def forbidden(bus, duration):
            self.fail("Bus6 must never run TDS")
        result = extend_day2_results([row], forbidden)["results"][0]
        for key in ("stable_lower_s", "unstable_upper_s", "interval_width_s", "failed_clearing_time_s"):
            self.assertEqual(result[key], row[key])
        self.assertEqual(result["reason"], "NON_CONVERGENT_MIDPOINT")
        self.assertEqual(result["extension_action"], "RETAINED_DAY2")
        self.assertEqual(result["extension_trials"], 0)
        self.assertEqual(result["total_trial_count"], 4)

    def test_missing_identity_seed_revalidated_once_then_reused_by_core(self):
        calls = []
        report = discover_bracket(lambda duration: (calls.append(duration) or
            outcome(duration, "STABLE" if duration < .22 else "UNSTABLE")))
        self.assertEqual(calls[0], SEED_DURATION_S)
        self.assertEqual(calls.count(SEED_DURATION_S), 1)
        self.assertEqual(calls.count(.25), 1)
        self.assertEqual(report["seed_revalidation_trials"], 1)
        self.assertEqual(report["search_status"], "RESOLVED")

    def test_exact_identity_required_including_program_and_config(self):
        identity = {"model_sha256": "model", "fault_bus": 1,
                    "integration_config": {"max_iter": 15},
                    "program_identity": {"plots.py": "old"}, "config_identity": {"baseline": "same"}}
        self.assertTrue(identity_matches(identity, dict(identity)))
        for key, change in [("fault_bus", 3), ("program_identity", {"plots.py": "new"}),
                            ("integration_config", {"max_iter": 30}), ("config_identity", {"baseline": "changed"})]:
            self.assertFalse(identity_matches(identity, {**identity, key: change}))
        self.assertFalse(identity_matches({}, {}))

    def test_binary_failure_keeps_existing_core_boundaries(self):
        calls = []
        def trial(duration):
            calls.append(duration)
            status = "UNSTABLE" if duration == .25 else "NON_CONVERGENT"
            return outcome(duration, status)
        report = discover_bracket(trial, seed=outcome(SEED_DURATION_S))
        self.assertEqual(report["reason"], "NON_CONVERGENT_MIDPOINT")
        self.assertEqual(report["stable_lower_s"], SEED_DURATION_S)
        self.assertEqual(report["unstable_upper_s"], .25)
        self.assertEqual(report["failed_clearing_time_s"], .21875)
        self.assertEqual(calls, [.25, .21875])

    def test_trial_exception_stops_preserves_error_and_checkpoints(self):
        checkpoints = []
        def trial(bus, duration):
            raise RuntimeError("mock execution failure")
        report = extend_day2_results([day2_row(1)], trial, seeds={1: outcome(SEED_DURATION_S)},
                                    on_checkpoint=lambda rows: checkpoints.append(rows))
        self.assertEqual(len(checkpoints), 2)
        self.assertEqual(report["results"][0]["extension_trials"], 1)
        self.assertIn("mock execution failure", report["extensions"]["1"]["trials"][0]["execution_error"])

    def test_extended_csv_json_complete_keep_null_and_total_trial_count(self):
        report = extend_day2_results([day2_row(1)], lambda bus, duration: outcome(duration),
                                    seeds={1: outcome(SEED_DURATION_S)})
        scratch = ROOT / ".cache/test_bracket"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temporary:
            output = Path(temporary)
            write_extended_summary(output, report["results"], metadata={"complete": True})
            value = json.loads((output / "cct_extended_summary.json").read_text(encoding="utf-8"))
            row = value["results"][0]
            self.assertTrue(set(EXTENDED_FIELDS).issubset(row))
            self.assertEqual(row["extension_trials"], 4)
            self.assertEqual(row["total_trial_count"], 6)
            self.assertIsNone(row["cct_estimate_s"])
            with (output / "cct_extended_summary.csv").open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(set(reader.fieldnames), set(EXTENDED_FIELDS))
                self.assertEqual(next(reader)["cct_estimate_s"], "")
            self.assertEqual(value["cct_ranking"], [])


if __name__ == "__main__":
    unittest.main()
