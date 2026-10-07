"""Day3A.5 topology, catalogue preservation and reuse tests; never start ANDES."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ieee39ts.main_scenarios import (MAIN_ROLE, STRESS_ROLE, build_main_models,
    choose_third_bus, inertia_inventory, preserve_bytes, reuse_decision)
from ieee39ts.scenarios import COMMON_SHEETS, read_books, sha256
from model_fixture import validation_archive


class MainScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "configs/renewable_main.json").read_text())
        cls.main = json.loads((ROOT / "cases/renewable/main/manifest.json").read_text())
        cls.stress = json.loads((ROOT / "cases/renewable/stress/manifest.json").read_text())
        cls.baseline = read_books(ROOT / "cases/renewable/S0_adapted_sg.xlsx")
        cls.books = [read_books(ROOT / "cases/renewable/main" / row["file"]) for row in cls.main["scenarios"]]
        cls.frozen = json.loads((ROOT / "configs/frozen_solver.json").read_text())["solver_config"]
        cache=ROOT/'.cache/public-model-tests';cache.mkdir(parents=True,exist_ok=True)
        temporary=tempfile.TemporaryDirectory(dir=cache)
        cls.addClassCleanup(temporary.cleanup)
        cls.archive=validation_archive(ROOT,Path(temporary.name)/'archive')
        # This unit test exercises exact identity against a known archived environment.
        # A machine's current Python patch release does not redefine that test input.
        cls.enterClassContext(patch('ieee39ts.main_scenarios.platform.python_version',return_value='3.13.15'))

    def test_topology_selects_bus32_independent_of_row_order(self):
        selection = choose_third_bus(self.baseline)
        by_bus = {row["bus"]: row for row in selection["candidate_metrics"]}
        self.assertEqual(selection["chosen_bus"], 32)
        self.assertEqual(by_bus[32]["hop_distances"], [8, 10])
        self.assertEqual(by_bus[35]["hop_distances"], [8, 8])
        reordered = deepcopy(self.baseline)
        reordered["Line"].reverse()
        self.assertEqual(choose_third_bus(reordered, candidates=(32, 35)), selection)

    def test_main_never_replaces_bus39_or_slack(self):
        self.assertEqual(self.main["scenario_class"], MAIN_ROLE)
        self.assertTrue(self.main["include_in_day3b_main_heatmap"])
        plans = [[], [37], [37, 38], [37, 38, 32]]
        for row, books, plan in zip(self.main["scenarios"], self.books, plans):
            self.assertEqual(row["renewable_buses"], plan)
            self.assertNotIn(39, plan)
            self.assertNotIn(31, plan)
            self.assertTrue({31, 39}.issubset({int(r["bus"]) for r in books["GENROU"]}))

    def test_stress_models_and_all_prior_artifacts_are_preserved(self):
        self.assertEqual(self.stress["scenario_class"], STRESS_ROLE)
        self.assertFalse(self.stress["include_in_day3b_main_heatmap"])
        self.assertEqual(len(self.stress["scenarios"]), 2)
        for row in self.stress["scenarios"]:
            self.assertIn(39, row["renewable_buses"])
            self.assertFalse(row["include_in_day3b_main_heatmap"])
            self.assertEqual(sha256(ROOT / "cases/renewable/stress" / row["file"]), row["sha256"])
            old = json.loads((self.archive / row["smoke_summary_reference"]).read_text())
            self.assertEqual(old["model_sha256"], row["sha256"])
        frozen = json.loads((ROOT / "tests/fixtures/model_validation/asset_hashes.json").read_text())
        self.assertFalse([path for path,digest in frozen.items() if not (ROOT/path).exists() or sha256(ROOT/path)!=digest])

    def test_share_and_inertia_increase_without_external_machine_jump(self):
        rows = self.main["scenarios"]
        shares = [row["expected_share_from_identical_static_plan"]["renewable_share_pct"] for row in rows]
        removed = [row["removed_sg_M_sum"] for row in rows]
        fractions = [row["removed_M_fraction_pct"] for row in rows]
        self.assertTrue(all(a < b for a,b in zip(shares, shares[1:])))
        self.assertTrue(all(a < b for a,b in zip(fractions, fractions[1:])))
        normal_max = max(row["M"] for row in inertia_inventory(self.archive) if row["bus"] not in (31,39))
        self.assertTrue(all(b-a <= normal_max + 1e-10 for a,b in zip(removed, removed[1:])))
        self.assertAlmostEqual(rows[-1]["removed_M_fraction_pct"], 12.336390356734029)
        for row in rows:
            self.assertAlmostEqual(row["remaining_sg_M_sum"] + row["removed_sg_M_sum"], row["original_sg_M_sum"])
        if all(row["renewable_share_pct"] is not None for row in rows):
            actual = [row["renewable_share_pct"] for row in rows]
            self.assertTrue(all(a < b for a,b in zip(actual, actual[1:])))
            for row in rows:
                self.assertAlmostEqual(row["renewable_share_pct"], row["expected_share_from_identical_static_plan"]["renewable_share_pct"])

    def test_new_s2_s3_structure_sn_and_foreign_keys(self):
        source_by_bus = {r["bus"]:r for r in self.baseline["GENROU"]}
        for index in (2,3):
            books = self.books[index]
            self.assertEqual(len(books["GENROU"]), 10-index)
            for name in ("TGOV1N", "IEEEX1", "IEEEST"):
                self.assertEqual(len(books[name]), 10-index)
            for name in ("REGCP1", "PLL2", "REECB1"):
                self.assertEqual(len(books[name]), index)
            for name in COMMON_SHEETS:
                self.assertEqual(books[name], self.baseline[name])
            sg = {r["idx"] for r in books["GENROU"]}
            avr = {r["idx"] for r in books["IEEEX1"]}
            self.assertTrue(all(r["syn"] in sg for r in books["TGOV1N"]+books["IEEEX1"]))
            self.assertTrue(all(r["avr"] in avr for r in books["IEEEST"]))
            static = {r["gen"] for r in books["GENROU"]}
            pll = {r["idx"]:r for r in books["PLL2"]}
            self.assertEqual({r["reg"] for r in books["REECB1"]}, {r["idx"] for r in books["REGCP1"]})
            for reg in books["REGCP1"]:
                self.assertEqual(reg["Sn"], source_by_bus[reg["bus"]]["Sn"])
                self.assertEqual(reg["gen"], source_by_bus[reg["bus"]]["gen"])
                self.assertEqual(pll[reg["pll"]]["bus"], reg["bus"])
                self.assertEqual((reg["gammap"],reg["gammaq"]),(1,1))
                self.assertNotIn(reg["gen"], static)
            self.assertEqual(len(static | {r["gen"] for r in books["REGCP1"]}), 10)

    def test_main_models_and_full_manifests_reproduce(self):
        cache = ROOT / ".cache/day3a5-tests"
        cache.mkdir(parents=True,exist_ok=True)
        report_path = self.archive / self.config["smoke_results"] / "scenario_summary.json"
        report = json.loads(report_path.read_text()) if report_path.exists() else None
        with tempfile.TemporaryDirectory(dir=cache) as temp:
            a, stress_a = build_main_models(self.archive, self.config, Path(temp)/"a", accepted_report=report)
            b, stress_b = build_main_models(self.archive, self.config, Path(temp)/"b", accepted_report=report)
            self.assertEqual(a,b)
            expected=deepcopy(self.main)
            expected['inertia_basis']['sha256']=sha256(self.archive/'results/day3a/scenario_smoke/S0/trajectory.npz')
            self.assertEqual(a,expected)
            self.assertEqual(stress_a,stress_b)
            self.assertEqual(stress_a,self.stress)
            for row in a["scenarios"]:
                self.assertEqual(sha256(Path(temp)/"a"/row["file"]),row["sha256"])
                self.assertEqual(sha256(Path(temp)/"b"/row["file"]),row["sha256"])

    def test_s0_s1_exact_identity_reused_and_new_cases_not_cached(self):
        for row in self.main["scenarios"]:
            decision = reuse_decision(self.archive,row,ROOT/"cases/renewable/main"/row["file"],self.frozen)
            self.assertEqual(decision["reused"],row["scenario_id"] in ("S0","S1"))
            if decision["reused"]:
                self.assertEqual(decision["reasons"],["EXACT_CASE_IDENTITY_MATCH"])
                report_path = self.archive / self.config["smoke_results"] / row["scenario_id"] / "summary.json"
                if report_path.exists():
                    cached = json.loads(report_path.read_text())
                    self.assertFalse(cached["tds_run_called"])
                    self.assertFalse(cached["tds_run_called_this_stage"])
                    self.assertTrue((report_path.parent / cached["trajectory_file"]).is_file())

    def test_reuse_rejects_model_or_solver_identity_mismatch(self):
        row = deepcopy(self.main["scenarios"][0])
        path = ROOT / "cases/renewable/main" / row["file"]
        row["sha256"] = "0"*64
        decision = reuse_decision(self.archive,row,path,self.frozen)
        self.assertFalse(decision["reused"])
        self.assertIn("MODEL_IDENTITY_MISMATCH",decision["reasons"])
        solver = deepcopy(self.frozen)
        solver["max_iter"] += 1
        decision = reuse_decision(self.archive,self.main["scenarios"][0],path,solver)
        self.assertFalse(decision["reused"])
        self.assertIn("SOLVER_IDENTITY_MISMATCH",decision["reasons"])

    def test_model_preservation_refuses_differing_bytes(self):
        cache = ROOT / ".cache/day3a5-tests"
        cache.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache) as temp:
            path=Path(temp)/"model.xlsx"
            preserve_bytes(path,b"original")
            stamp=path.stat().st_mtime_ns
            preserve_bytes(path,b"original")
            self.assertEqual(path.stat().st_mtime_ns,stamp)
            with self.assertRaisesRegex(ValueError,"overwrite"):
                preserve_bytes(path,b"different")
            self.assertEqual(path.read_bytes(),b"original")


if __name__ == "__main__":
    unittest.main()
