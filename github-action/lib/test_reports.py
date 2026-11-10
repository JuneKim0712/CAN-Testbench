import json
from pathlib import Path
import tempfile
import unittest
from pages_compiler import compile_run_record


class ReportTests(unittest.TestCase):
    def test_missing_evidence_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                compile_run_record(temp, run_id='1', artifacts_dir=temp)

    def test_one_authoritative_trace_and_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            artifacts = Path(temp) / 'artifacts'
            artifacts.mkdir()
            frame = dict(source='physical_bus', direction='rx', session_id='fixture',
                         sequence=1, timestamp=100, id='0x001', dlc=1, data='00')
            report = dict(run_id='1', subsystem='custom_fw', passed=True,
                          tests=[dict(status='PASS', name='example')], can_traffic=[frame, frame])
            (artifacts / 'custom_test_results.json').write_text(json.dumps(report))
            (artifacts / 'static_check.json').write_text(json.dumps(dict(run_id='1', status='passed')))
            (artifacts / 'custom_fw_can_trace.jsonl').write_text(json.dumps(frame))
            runs = compile_run_record(temp, '1', artifacts_dir=artifacts)
            self.assertEqual('passed', runs[0]['status'])
            self.assertEqual('custom_fw', runs[0]['tests'][0]['subsystem'])
            self.assertEqual(1, len(runs[0]['can_packets']))
            self.assertEqual('fixture', runs[0]['can_packets'][0]['session_id'])
            report['passed'] = False
            (artifacts / 'custom_test_results.json').write_text(json.dumps(report))
            self.assertEqual('failed', compile_run_record(temp, '1', artifacts_dir=artifacts)[0]['status'])

    def test_stale_report_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / 'old_test_results.json').write_text(json.dumps(dict(run_id='old')))
            with self.assertRaises(ValueError):
                compile_run_record(temp, 'new', artifacts_dir=temp)
