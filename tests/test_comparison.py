"""Pure Day3B matrix, CCT composition, metrics and figure-input tests."""
from copy import deepcopy
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from ieee39ts.comparison import (BUSES,FIELDS,cache_identity_matches,load_main_manifest,matrix,reference_extras,run_comparison,search_cell,write_summary)
from ieee39ts.comparison_plots import adjacent_resolved_segments,heatmap_data
from ieee39ts.bracket import discover_bracket
from ieee39ts.cct import search_cct
from ieee39ts.types import FaultResult,SimulationSettings,Trajectory


def outcome(duration,status="STABLE",bus=16,**metadata):
    trace=Trajectory(np.array([0.,1.,1.13,8.]),np.zeros((4,2)),np.ones((4,2)),
        np.array([[1.,1.],[.02,.8],[.9,.95],[1.,1.]]),np.array(["g1","g2"]),
        np.array([30,39]),np.array([2.,1.]),np.array([bus,39]))
    summary={"clearing_duration_s":duration,"fault_bus":bus,"fault_clear_absolute_s":1+duration,
        "stability_status":status,"simulation_status":"COMPLETED","max_angle_separation_deg":100.,
        "max_speed_deviation_pu":.02,"runtime_s":.1,"tail_invalid":False,**metadata}
    return FaultResult(summary,trace,{"valid_mask":np.ones(4,dtype=bool),"PLL2_frequency_hz":np.array([[60.],[60.2],[60.1],[60.]])})


class ComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest=load_main_manifest(ROOT,ROOT/"cases/renewable/main/manifest.json")

    def test_exact_twenty_unique_cells_and_fixed_buses(self):
        rows=matrix(self.manifest)
        self.assertEqual(len(rows),20)
        self.assertEqual(len({(r['scenario_id'],r['fault_bus']) for r in rows}),20)
        self.assertEqual({r['fault_bus'] for r in rows},set(BUSES))
        self.assertNotIn(6,{r['fault_bus'] for r in rows})

    def test_only_main_manifest_path_allowed(self):
        for rel in ['cases/renewable/manifest.json','cases/renewable/stress/manifest.json','cases/manifest.json']:
            with self.assertRaisesRegex(ValueError,"main manifest"):
                load_main_manifest(ROOT,ROOT/rel)

    def test_stress_role_rejected_even_at_main_path(self):
        bad=deepcopy(self.manifest);bad['scenario_class']='external-equivalent_stress_scenarios'
        with patch.object(Path,'read_text',return_value=json.dumps(bad)):
            with self.assertRaisesRegex(ValueError,'Stress'):
                load_main_manifest(ROOT,ROOT/'cases/renewable/main/manifest.json')

    def test_share_and_each_cell_model_hash_come_from_manifest(self):
        custom=deepcopy(self.manifest);custom['scenarios'][2]['renewable_share_pct']=23.456789
        rows=matrix(custom)
        self.assertEqual(len({row['model_sha256'] for row in rows}),4)
        for row in rows:
            source=next(s for s in custom['scenarios'] if s['scenario_id']==row['scenario_id'])
            self.assertEqual(row['model_sha256'],source['sha256'])
            self.assertEqual(row['renewable_share_pct'],source['renewable_share_pct'])

    def test_official_or_other_scenario_cache_never_matches(self):
        wanted={'model_family':'adapted_main','scenario_id':'S0','model_sha256':'main','fault_bus':16}
        self.assertTrue(cache_identity_matches(wanted,wanted))
        for changed in [{'model_family':'ieee39_official'},{'model_sha256':'official'},{'scenario_id':'S1'},{'fault_bus':10}]:
            self.assertFalse(cache_identity_matches({**wanted,**changed},wanted))
        self.assertFalse(cache_identity_matches({'model_family':'ieee39_official'},{'model_family':'ieee39_official'}))

    def test_initial_verified_bracket_calls_original_core(self):
        calls=[]
        def trial(duration):
            calls.append(duration)
            return outcome(duration,'STABLE' if duration<.17 else 'UNSTABLE')
        with patch('ieee39ts.comparison.search_cct',wraps=search_cct) as core:
            report=search_cell(trial)
        core.assert_called_once()
        self.assertEqual(calls[:2],[.03125,.1953125])
        self.assertEqual(calls.count(.03125),1);self.assertEqual(calls.count(.1953125),1)
        self.assertEqual(report['search_status'],'RESOLVED')
        self.assertLessEqual(report['interval_width_s'],1/128)

    def test_extension_calls_original_discovery_and_stops_at_first_unstable(self):
        calls=[]
        def trial(duration):
            calls.append(duration)
            return outcome(duration,'STABLE' if duration<.2 else 'UNSTABLE')
        with patch('ieee39ts.comparison.discover_bracket',wraps=discover_bracket) as discovery:
            report=search_cell(trial)
        discovery.assert_called_once()
        self.assertEqual(calls[:3],[.03125,.1953125,.25])
        self.assertNotIn(.3125,calls)
        self.assertEqual(report['search_status'],'RESOLVED')

    def test_nonconvergent_midpoint_keeps_both_verified_bounds(self):
        calls=[]
        def trial(duration):
            calls.append(duration)
            return outcome(duration,'STABLE' if duration==.03125 else 'UNSTABLE' if duration==.1953125 else 'NON_CONVERGENT')
        report=search_cell(trial)
        self.assertEqual(report['reason'],'NON_CONVERGENT_MIDPOINT')
        self.assertEqual((report['stable_lower_s'],report['unstable_upper_s']),(.03125,.1953125))
        self.assertIsNone(report['cct_estimate_s'])
        self.assertEqual(len(calls),3)

    def test_quality_failure_stops_without_becoming_unstable(self):
        calls=[]
        def trial(duration):
            calls.append(duration)
            return outcome(duration,'STABLE' if duration==.03125 else 'UNSTABLE',tail_invalid=duration!=.03125)
        report=search_cell(trial)
        self.assertEqual(report['search_status'],'UNRESOLVED')
        self.assertIsNone(report['unstable_upper_s']);self.assertIsNone(report['cct_estimate_s'])
        self.assertEqual(calls,[.03125,.1953125])

    def test_half_second_stable_is_lower_bound_and_null_estimate(self):
        calls=[]
        def trial(duration):calls.append(duration);return outcome(duration)
        report=search_cell(trial)
        self.assertEqual(calls,[.03125,.1953125,.25,.3125,.375,.5])
        self.assertEqual(report['stable_lower_s'],.5)
        self.assertIsNone(report['unstable_upper_s']);self.assertIsNone(report['cct_estimate_s'])
        self.assertIn('> 500',report['cct_range_statement'])

    def test_heatmap_unresolved_stays_nan_and_lines_do_not_cross_gaps(self):
        rows=matrix(self.manifest)
        for row in rows:row.update(search_status='UNRESOLVED',cct_reason='NON_CONVERGENT_MIDPOINT',cct_estimate_s=None)
        values,labels=heatmap_data(rows)
        self.assertTrue(np.isnan(values).all());self.assertTrue((labels=='NC').all())
        rows[0].update(search_status='RESOLVED',cct_estimate_s=.2)
        rows[10].update(search_status='RESOLVED',cct_estimate_s=.3)
        rows[15].update(search_status='RESOLVED',cct_estimate_s=.4)
        self.assertEqual([(a['scenario_id'],b['scenario_id']) for a,b in adjacent_resolved_segments(rows,10)],[('S2','S3')])
        rows[1]['cct_reason']='NO_UNSTABLE_ENDPOINT_WITHIN_0P5S'
        values,labels=heatmap_data(rows)
        self.assertEqual(labels[0,1],'>500');self.assertTrue(np.isnan(values[0,1]))

    def test_all_references_are_once_at_125_ms_and_conditions_identical(self):
        calls=[]
        def trial(scenario,bus,duration,role):calls.append((scenario['scenario_id'],bus,duration,role));return outcome(duration,bus=bus)
        rows=run_comparison(self.manifest,trial)
        reference=[c for c in calls if c[3]=='reference']
        self.assertEqual(len(reference),20)
        self.assertTrue(all(c[2]==.125 for c in reference))
        specs=[SimulationSettings(bus=bus) for scenario in self.manifest['scenarios'] for bus in BUSES]
        self.assertTrue(all((s.fault_start_s,s.observation_end_s,s.angle_limit_deg,s.fault_reactance_pu,s.time_step_s)==(1.,8.,180.,1e-4,1/128) for s in specs))
        self.assertTrue(all(row['metrics_clear_duration_s']==.125 for row in rows))

    def test_reference_failure_stops_cell_but_keeps_all_twenty_rows(self):
        calls=[]
        def trial(scenario,bus,duration,role):calls.append(role);return outcome(duration,'NON_CONVERGENT',bus=bus)
        rows=run_comparison(self.manifest,trial)
        self.assertEqual(calls,['reference']*20)
        self.assertEqual(len(rows),20)
        self.assertTrue(all(row['cct_estimate_s'] is None and row['trial_count']==0 for row in rows))

    def test_light_diagnostics_use_valid_samples_without_new_label(self):
        result=outcome(.125)
        metrics=reference_extras(result)
        self.assertAlmostEqual(metrics['max_abs_pll_frequency_deviation_hz'],.2)
        self.assertAlmostEqual(metrics['postfault_min_bus_voltage_pu'],.9)
        self.assertEqual(result.summary['stability_status'],'STABLE')

    def test_summary_csv_json_has_twenty_complete_rows_and_nulls(self):
        rows=run_comparison(self.manifest,lambda s,b,d,r:outcome(d,bus=b))
        cache=ROOT/'.cache/day3b-tests';cache.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache) as temp:
            write_summary(Path(temp),rows,{'complete':True})
            report=json.loads((Path(temp)/'scenario_fault_summary.json').read_text())
            with (Path(temp)/'scenario_fault_summary.csv').open(newline='',encoding='utf-8') as handle:
                csv_rows=list(csv.DictReader(handle))
            self.assertEqual(len(report['results']),20);self.assertEqual(len(csv_rows),20)
            self.assertTrue(set(FIELDS).issubset(csv_rows[0]))
            self.assertTrue(all(r['cct_estimate_s'] is None for r in report['results']))
            self.assertTrue(all(r['cct_estimate_s']=='' for r in csv_rows))


if __name__=='__main__':unittest.main()
