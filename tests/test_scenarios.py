"""Pure workbook and injection-accounting tests: no ANDES, PFlow or TDS."""
from copy import deepcopy
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ieee39ts.scenarios import (COMMON_SHEETS, build_models, read_books,
                               renewable_share, replace_generators, sha256)


class ScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "configs/renewable_scenarios.json").read_text())
        cls.baseline = read_books(ROOT / cls.config["adapted_source"])
        cls.pilot = read_books(ROOT / cls.config["pilot_source"])
        cls.manifest = json.loads((ROOT / "cases/renewable/manifest.json").read_text())
        cls.books = [read_books(ROOT / "cases/renewable" / row["file"]) for row in cls.manifest["scenarios"]]

    def test_s0_exact_source_bytes_and_ten_sg(self):
        self.assertEqual(sha256(ROOT / "cases/renewable/S0_adapted_sg.xlsx"),
                         sha256(ROOT / self.config["adapted_source"]))
        self.assertEqual(len(self.books[0]["GENROU"]), 10)
        self.assertNotIn("REGCP1", self.books[0])

    def test_s1_nine_sg_one_renewable(self):
        self.assert_counts(1)

    def test_s2_eight_sg_two_renewables(self):
        self.assert_counts(2)

    def test_s3_seven_sg_three_renewables(self):
        self.assert_counts(3)

    def assert_counts(self, index):
        books = self.books[index]
        self.assertEqual(len(books["GENROU"]), 10-index)
        for name in ("REGCP1", "PLL2", "REECB1"):
            self.assertEqual(len(books[name]), index)
        for name in ("TGOV1N", "IEEEX1", "IEEEST"):
            self.assertEqual(len(books[name]), 10-index)

    def test_duplicate_buses_rejected(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            replace_generators(self.baseline, self.pilot, [37, 37])

    def test_slack_replacement_rejected(self):
        with self.assertRaisesRegex(ValueError, "Slack"):
            replace_generators(self.baseline, self.pilot, [37, 31])

    def test_missing_sg_rejected(self):
        with self.assertRaisesRegex(ValueError, "online GENROU"):
            replace_generators(self.baseline, self.pilot, [16])

    def test_controller_removal_follows_foreign_keys(self):
        baseline = deepcopy(self.baseline)
        baseline["TGOV1N"][7]["idx"] = "independent_governor_id"
        baseline["IEEEX1"][7]["idx"] = "independent_exciter_id"
        baseline["IEEEST"][7].update(idx="independent_pss_id", avr="independent_exciter_id")
        books, replacements = replace_generators(baseline, self.pilot, [37])
        removed = replacements[0]["removed"]
        self.assertEqual(removed["TGOV1N"], ["independent_governor_id"])
        self.assertEqual(removed["IEEEX1"], ["independent_exciter_id"])
        self.assertEqual(removed["IEEEST"], ["independent_pss_id"])
        for name, ids in removed.items():
            self.assertTrue(set(ids).isdisjoint(r["idx"] for r in books[name]))
        sg = {row["idx"] for row in books["GENROU"]}
        exc = {row["idx"] for row in books["IEEEX1"]}
        self.assertTrue(all(row["syn"] in sg for row in books["TGOV1N"] + books["IEEEX1"]))
        self.assertTrue(all(row["avr"] in exc for row in books["IEEEST"]))

    def test_dynamic_sources_and_controller_mappings(self):
        for scenario, books in zip(self.manifest["scenarios"][1:], self.books[1:]):
            ren_by_id = {row["idx"]: row for row in books["REGCP1"]}
            pll_by_id = {row["idx"]: row for row in books["PLL2"]}
            sg_static = {row["gen"] for row in books["GENROU"]}
            self.assertTrue(sg_static.isdisjoint(r["gen"] for r in books["REGCP1"]))
            for reg in books["REGCP1"]:
                self.assertEqual(pll_by_id[reg["pll"]]["bus"], reg["bus"])
                self.assertIn(reg["bus"], scenario["renewable_buses"])
                self.assertEqual(reg["gammap"], 1)
                self.assertEqual(reg["gammaq"], 1)
            self.assertEqual({r["reg"] for r in books["REECB1"]}, set(ren_by_id))
            self.assertEqual(len(sg_static | {r["gen"] for r in books["REGCP1"]}), 10)

    def test_sn_matches_original_and_template_normalization(self):
        originals = {row["bus"]: row for row in self.baseline["GENROU"]}
        pilot_sn = self.pilot["REGCP1"][0]["Sn"]
        for books in self.books[1:]:
            for reg, reec in zip(books["REGCP1"], books["REECB1"]):
                self.assertEqual(reg["Sn"], originals[reg["bus"]]["Sn"])
                self.assertGreaterEqual(reg["Sn"], originals[reg["bus"]]["Sn"])
                for key in ("Kqv", "Iqh1", "Iql1"):
                    self.assertAlmostEqual(reec[key] / reg["Sn"], self.pilot["REECB1"][0][key] / pilot_sn)

    def test_all_common_data_and_remaining_sg_parameters_unchanged(self):
        for books in self.books:
            for name in COMMON_SHEETS:
                self.assertEqual(books[name], self.baseline[name])
            for name in ("GENROU", "TGOV1N", "IEEEX1", "IEEEST"):
                original = {row["idx"]: row for row in self.baseline[name]}
                for row in books[name]:
                    self.assertEqual({k:v for k,v in row.items() if k != "uid"},
                                     {k:v for k,v in original[row["idx"]].items() if k != "uid"})

    def test_pilot_crosscheck_only_documented_differences(self):
        books = self.books[1]
        # Reindexing affects only uid. Every retained controller still matches the pilot.
        for name in ("GENROU", "TGOV1N", "IEEEX1", "IEEEST"):
            self.assertEqual([{k:v for k,v in r.items() if k != "uid"} for r in books[name]],
                             [{k:v for k,v in r.items() if k != "uid"} for r in self.pilot[name]])
        for name in COMMON_SHEETS:
            pilot = deepcopy(self.pilot[name])
            if name == "PV":
                for row in pilot:
                    if row["bus"] == 37:
                        row["Sn"] = 970.2
            self.assertEqual(books[name], pilot)
        for name in ("PLL2", "REGCP1", "REECB1"):
            allowed = {"REGCP1": {"Sn", "gammap", "gammaq"},
                       "REECB1": {"Kqv", "Iqh1", "Iql1"}, "PLL2": set()}[name]
            actual, pilot = books[name][0], self.pilot[name][0]
            self.assertEqual({k:v for k,v in actual.items() if k not in allowed},
                             {k:v for k,v in pilot.items() if k not in allowed})

    def test_share_uses_actual_static_p_and_increases_monotonically(self):
        with (ROOT / "docs/day3_generator_candidates.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        static = [{"static_gen_id": int(row["static_gen_id"]), "online": True,
                   "P0_MW": float(row["P0_MW"])} for row in rows]
        shares = [renewable_share(static, books.get("REGCP1", [])) for books in self.books]
        self.assertTrue(all(a["renewable_share_pct"] < b["renewable_share_pct"] for a,b in zip(shares, shares[1:])))
        self.assertEqual(shares[0]["renewable_P_MW"], 0)
        self.assertAlmostEqual(shares[3]["renewable_P_MW"], 2370)
        self.assertAlmostEqual(shares[3]["total_generation_P_MW"], 6105.148412289636)
        self.assertAlmostEqual(shares[3]["renewable_share_pct"], 100*2370/6105.148412289636)

    def test_share_rejects_double_counting_and_offline_reference(self):
        static = [{"static_gen_id": 1, "online": True, "P0_MW": 100},
                  {"static_gen_id": 2, "online": False, "P0_MW": 999}]
        self.assertEqual(renewable_share(static, [{"gen": 1}])["renewable_share_pct"], 100)
        with self.assertRaisesRegex(ValueError, "one renewable"):
            renewable_share(static, [{"gen": 1}, {"gen": 1}])
        with self.assertRaisesRegex(ValueError, "offline"):
            renewable_share(static, [{"gen": 2}])

    def test_model_bytes_and_manifest_are_reproducible(self):
        cache = ROOT / ".cache/day3a-tests"
        cache.mkdir(parents=True, exist_ok=True)
        accepted_path = ROOT / "tests/fixtures/model_validation/scenario_summary.json"
        accepted = json.loads(accepted_path.read_text()) if accepted_path.exists() else None
        with tempfile.TemporaryDirectory(dir=cache) as temp:
            output_a, output_b = Path(temp) / "a", Path(temp) / "b"
            a = build_models(ROOT, self.config, output_a, smoke_report=accepted)
            b = build_models(ROOT, self.config, output_b, smoke_report=accepted)
            self.assertEqual(a, b)
            self.assertEqual(a, self.manifest)
            for row in a["scenarios"]:
                self.assertEqual(sha256(output_a / row["file"]), row["sha256"])
                self.assertEqual(sha256(output_b / row["file"]), row["sha256"])


if __name__ == "__main__":
    unittest.main()
