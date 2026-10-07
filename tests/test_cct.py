"""Callback-based binary-search tests: no real simulations."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ieee39ts.cct import search_cct
from ieee39ts.types import SearchSettings


def outcome(status):
    return {"stability_status": status, "simulation_status": "MOCK_ACCEPTED_TRIAL"}


class BinarySearchTests(unittest.TestCase):
    def test_stable_increases_lower_unstable_decreases_upper_and_midpoint(self):
        result = search_cct(SearchSettings(), lambda duration: outcome("STABLE" if duration < 25 / 128 else "UNSTABLE"))
        self.assertEqual(result["search_status"], "RESOLVED")
        self.assertEqual([r["clearing_ticks"] for r in result["trials"]], [4, 32, 18, 25, 21, 23, 24])
        self.assertEqual(result["stable_lower_s"], 24 / 128)
        self.assertEqual(result["unstable_upper_s"], 25 / 128)
        self.assertEqual(result["interval_width_s"], 1 / 128)
        self.assertEqual(result["cct_estimate_s"], 24.5 / 128)

    def test_failure_midpoint_does_not_change_either_boundary(self):
        def runner(duration):
            return outcome("STABLE" if duration == 4 / 128 else "UNSTABLE" if duration == 32 / 128 else "NON_CONVERGENT")
        result = search_cct(SearchSettings(), runner)
        self.assertEqual(result["search_status"], "UNRESOLVED")
        self.assertIsNone(result["cct_estimate_s"])
        self.assertEqual(result["stable_lower_s"], 4 / 128)
        self.assertEqual(result["unstable_upper_s"], 32 / 128)
        self.assertEqual(result["failed_clearing_time_s"], 18 / 128)
        self.assertEqual(result["trial_count"], 3)

    def test_failure_after_successful_updates_preserves_latest_bracket(self):
        def runner(duration):
            return outcome("NON_CONVERGENT" if duration == 25 / 128 else "STABLE" if duration < 25 / 128 else "UNSTABLE")
        result = search_cct(SearchSettings(), runner)
        self.assertEqual(result["stable_lower_s"], 18 / 128)
        self.assertEqual(result["unstable_upper_s"], 32 / 128)
        self.assertEqual(result["failed_clearing_time_s"], 25 / 128)
        self.assertIsNone(result["cct_estimate_s"])

    def test_missing_stable_endpoint(self):
        result = search_cct(SearchSettings(), lambda duration: outcome("UNSTABLE"))
        self.assertEqual(result["reason"], "NO_STABLE_ENDPOINT")
        self.assertEqual(result["search_status"], "UNRESOLVED")
        self.assertIsNone(result["stable_lower_s"])
        self.assertIsNone(result["cct_estimate_s"])
        self.assertEqual(result["trial_count"], 1)

    def test_missing_unstable_endpoint(self):
        result = search_cct(SearchSettings(), lambda duration: outcome("STABLE"))
        self.assertEqual(result["reason"], "NO_UNSTABLE_ENDPOINT")
        self.assertEqual(result["stable_lower_s"], 32 / 128)
        self.assertIsNone(result["unstable_upper_s"])
        self.assertIsNone(result["cct_estimate_s"])

    def test_non_convergent_stable_endpoint(self):
        result = search_cct(SearchSettings(), lambda duration: outcome("NON_CONVERGENT"))
        self.assertIsNone(result["stable_lower_s"])
        self.assertIsNone(result["unstable_upper_s"])
        self.assertEqual(result["failed_clearing_time_s"], 4 / 128)

    def test_non_convergent_unstable_endpoint(self):
        result = search_cct(SearchSettings(), lambda duration: outcome("STABLE" if duration == 4 / 128 else "NON_CONVERGENT"))
        self.assertEqual(result["stable_lower_s"], 4 / 128)
        self.assertIsNone(result["unstable_upper_s"])
        self.assertEqual(result["failed_clearing_time_s"], 32 / 128)

    def test_iteration_budget_does_not_produce_estimate(self):
        result = search_cct(SearchSettings(max_iterations=0), lambda duration: outcome("STABLE" if duration < 25 / 128 else "UNSTABLE"))
        self.assertEqual(result["reason"], "MAXIMUM_ITERATIONS_REACHED")
        self.assertIsNone(result["cct_estimate_s"])
        self.assertEqual(result["trial_count"], 2)

    def test_runner_exception_is_persisted_as_unresolved(self):
        def runner(duration):
            raise RuntimeError("simulated integration exception")
        result = search_cct(SearchSettings(), runner)
        self.assertEqual(result["search_status"], "UNRESOLVED")
        self.assertIn("integration exception", result["trials"][0]["execution_error"])

    def test_checkpoint_keeps_all_trials(self):
        records = []
        result = search_cct(SearchSettings(), lambda duration: outcome("STABLE" if duration < 25 / 128 else "UNSTABLE"), on_trial=records.append)
        self.assertEqual(records, result["trials"])

    def test_grid_alignment_and_tolerance_validation(self):
        for settings in (SearchSettings(tolerance_s=0.001), SearchSettings(tc_min_s=0.03),
                         SearchSettings(tolerance_s=0), SearchSettings(time_step_s=0),
                         SearchSettings(max_iterations=-1)):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                settings.grid_ticks()

    def test_already_narrow_bracket_only_validates_endpoints(self):
        settings = SearchSettings(tc_min_s=24 / 128, tc_max_s=25 / 128)
        result = search_cct(settings, lambda duration: outcome("STABLE" if duration < 25 / 128 else "UNSTABLE"))
        self.assertEqual(result["trial_count"], 2)
        self.assertEqual(result["iterations"], 0)
        self.assertEqual(result["cct_estimate_s"], 24.5 / 128)


if __name__ == "__main__":
    unittest.main()
