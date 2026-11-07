"""Parser fixtures are software tests, never hardware pass evidence."""
import unittest
from unittest.mock import patch
import unity_parser


class SerialFixture:
    def __init__(self, lines):
        self.lines = iter(lines)

    def readline(self):
        return next(self.lines, b'')

    def close(self):
        pass


class UnityResultTests(unittest.TestCase):
    def run_fixture(self, lines):
        with patch.object(unity_parser.serial, 'Serial', return_value=SerialFixture(lines)), \
                patch.object(unity_parser.LiveCANMonitor, 'start'), \
                patch.object(unity_parser.LiveCANMonitor, 'join'):
            return unity_parser.parse_unity_stream('fixture', timeout=0.01)

    def test_completed_pass(self):
        self.assertEqual(0, self.run_fixture([b'test.c:1:example:PASS\n',
                                            b'1 Tests 0 Failures 0 Ignored\n']))

    def test_partial_output_cannot_pass(self):
        self.assertEqual(1, self.run_fixture([b'test.c:1:example:PASS\n']))

    def test_missing_results_cannot_pass(self):
        self.assertEqual(1, self.run_fixture([b'4 Tests 0 Failures 0 Ignored\n']))

    def test_failure_counts(self):
        for count in (1, 10, 100):
            self.assertEqual(1, self.run_fixture([
                f'{count} Tests {count} Failures 0 Ignored\n'.encode()]))

    def test_contradictory_summary(self):
        self.assertEqual(1, self.run_fixture([b'test.c:1:example:FAIL:bad\n',
                                            b'1 Tests 0 Failures 0 Ignored\n']))

    def test_truncated_summary_cannot_pass(self):
        self.assertEqual(1, self.run_fixture([b'test.c:1:example:PASS\n',
                                            b'1 Tests 0 Failures\n']))

    def test_all_ignored_cannot_pass(self):
        self.assertEqual(1, self.run_fixture([b'test.c:1:example:IGNORE\n',
                                            b'1 Tests 0 Failures 1 Ignored\n']))


if __name__ == '__main__':
    unittest.main()
