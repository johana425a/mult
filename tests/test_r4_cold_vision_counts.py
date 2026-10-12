"""Pure receipt-predicate regression; no model, service or filesystem mutation."""
from pathlib import Path
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[1]
mapping = runpy.run_path(str(ROOT / 'reports/run_r4_cold_feature_acceptance.py'),
                        run_name='cold_vision_predicate_test')['explicit_vision_mapping']


class ExactVisionCounts(unittest.TestCase):
    def test_exact_fixture_mapping(self):
        self.assertTrue(mapping('Left: 20 red balls. Right: 80 blue balls.'))
        self.assertTrue(mapping('Left side: red, 20 balls. Right side: blue, 80 balls.'))

    def test_larger_counts_do_not_pass_as_substrings(self):
        self.assertFalse(mapping('Left: 200 red balls. Right: 800 blue balls.'))
        self.assertFalse(mapping('Left: red 120 balls; Right: blue 180 balls.'))

    def test_swapped_mapping_does_not_pass(self):
        self.assertFalse(mapping('Left: 80 red balls. Right: 20 blue balls.'))
        self.assertFalse(mapping('Left: 20 blue balls. Right: 80 red balls.'))


if __name__ == '__main__':
    unittest.main()
