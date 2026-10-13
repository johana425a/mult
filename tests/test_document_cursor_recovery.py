"""Cursor inputs that models commonly send must not cause a permanent
"pagination position is invalid" loop. Real reader, synthetic text files only.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from integration import document_jobs as jobs
from scripts import workspace_document_reader as reader


ROOT = Path(__file__).resolve().parents[1]


class CursorRecoveryTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'runtime').mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='cursor-recovery-', dir=ROOT / 'runtime')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        lines = [f'Synthetic line {number:03d} ' + 'x' * 40 + '\n' for number in range(1, 61)]
        (self.root / 'notes.txt').write_text(''.join(lines), encoding='utf-8')

    def read(self, **options):
        return reader.handle_request({'root': str(self.root), 'path': 'notes.txt', 'max_chars': 600, **options})

    def test_placeholder_cursor_values_read_from_the_beginning(self):
        for placeholder in ['', '  ', 'null', 'None', 'undefined', '0', 'start', '""']:
            with self.subTest(cursor=placeholder):
                value = self.read(cursor=placeholder)
                self.assertTrue(value['ok'], value)
                self.assertEqual(value['units'][0]['unit_index'], 1)

    def test_blank_numeric_options_use_defaults(self):
        value = self.read(cursor='', start_unit=0, max_units='', ocr='')
        self.assertTrue(value['ok'], value)
        self.assertEqual(value['units'][0]['unit_index'], 1)
        value = reader.handle_request({'root': str(self.root), 'path': 'notes.txt', 'max_chars': '600', 'start_unit': '5'})
        self.assertTrue(value['ok'], value)
        self.assertEqual(value['units'][0]['unit_index'], 5)

    def test_cursor_without_padding_or_with_quotes_continues_exactly(self):
        digest = self.read()['document_sha256']
        # Pick a real position whose token carries base64 padding to strip.
        cursor = next(token for token in (reader.cursor_encode(digest, index, 0) for index in range(1, 60)) if token.endswith('='))
        expected = self.read(cursor=cursor)
        self.assertTrue(expected['ok'], expected)
        for damaged in [cursor.rstrip('='), f'"{cursor}"', f' {cursor}\n', cursor.replace('-', '+').replace('_', '/')]:
            with self.subTest(cursor=damaged[:12]):
                value = self.read(cursor=damaged)
                self.assertTrue(value['ok'], value)
                self.assertEqual(value['text'], expected['text'])

    def test_every_page_offers_a_plain_integer_fallback(self):
        value = self.read()
        self.assertTrue(value['truncated'])
        self.assertEqual(value['navigation']['next_cursor'], value['next_cursor'])
        fallback = self.read(start_unit=value['next_start_unit'])
        cursor = self.read(cursor=value['next_cursor'])
        # start_unit restarts the unit holding the cursor: it may repeat text
        # but can never start after the cursor position.
        self.assertLessEqual(fallback['units'][0]['unit_index'], cursor['units'][0]['unit_index'])
        last = self.read(start_unit=60)
        self.assertFalse(last['truncated'])
        self.assertTrue(last['navigation']['done'])
        self.assertIsNone(last['next_start_unit'])

    def test_page_number_sent_as_cursor_becomes_start_unit(self):
        for text in ['7', 'page 7', 'page=7', 'start_unit=7', 'p7']:
            with self.subTest(cursor=text):
                value = self.read(cursor=text)
                self.assertTrue(value['ok'], value)
                self.assertEqual(value['units'][0]['unit_index'], 7)

    def test_valid_cursor_wins_over_conflicting_start_unit(self):
        cursor = self.read()['next_cursor']
        both = self.read(cursor=cursor, start_unit=1)
        self.assertTrue(both['ok'], both)
        self.assertEqual(both['text'], self.read(cursor=cursor)['text'])
        junk = self.read(cursor='not a cursor!', start_unit=9)
        self.assertTrue(junk['ok'], junk)
        self.assertEqual(junk['units'][0]['unit_index'], 9)

    def test_damaged_cursor_error_explains_recovery(self):
        value = self.read(cursor='eyJub3QiOiJ0aGlzIGRvY3VtZW50In0')
        self.assertFalse(value['ok'])
        self.assertEqual(value['error']['code'], 'INVALID_CURSOR')
        self.assertIn('start_unit', value['error']['message'])
        beyond = self.read(start_unit=500)
        self.assertEqual(beyond['error']['code'], 'POSITION_OUT_OF_RANGE')
        self.assertIn('60', beyond['error']['message'])

    def test_explicit_out_of_range_or_remote_options_still_fail(self):
        for options in [{'max_units': 41}, {'max_chars': 200000}, {'ocr': 'cloud'}]:
            with self.subTest(options=options):
                value = self.read(**options)
                self.assertFalse(value['ok'])
                self.assertEqual(value['error']['code'], 'INVALID_REQUEST')

    def test_job_queue_normalizes_engine_and_rejects_remote_engines(self):
        normalized = reader.normalize_read_request({'engine': 'MinerU', 'tier': 'vlm', 'cursor': ''})
        self.assertEqual(normalized, {'engine': 'mineru', 'tier': 'advanced'})
        for engine in ['mineru-cloud', 'api']:
            with self.subTest(engine=engine), self.assertRaises(reader.ReaderError):
                reader.normalize_read_request({'engine': engine})
        result = jobs.handle({'root': str(self.root), 'path': 'notes.txt', 'action': 'coverage', 'cursor': ''},
                             test_root=str(self.root / 'state'))
        self.assertTrue(result['ok'], result)


if __name__ == '__main__':
    unittest.main()
