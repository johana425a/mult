"""Pure synthetic dictionaries exercise structured paging; no parser/model runs."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from integration import document_jobs as jobs


DIGEST = 'a' * 64
DESTINATION = Path('D:/synthetic-unused-structure-cache')


def cursor(index, offset, digest=DIGEST, *, version_cursor=None):
    value = json.loads(base64.urlsafe_b64decode(jobs.reader.cursor_encode(digest, index, offset)))
    value['engine'] = 'mineru'
    if version_cursor:
        # Borrow the version issued by the implementation rather than copying
        # its signature algorithm into a test helper.
        value['text_version'] = json.loads(base64.urlsafe_b64decode(version_cursor))['text_version']
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode()


def original_page(number, text='native text', **extra):
    return {
        'unit_index': number,
        'unit_text_sha256': hashlib.sha256(text.encode()).hexdigest(),
        'locator': {'page': number, 'page_kind': 'pdf_physical'},
        'text': text,
        'char_start': 0,
        'char_end': len(text),
        'total_chars': len(text),
        'status': 'ready',
        'extraction': 'text',
        'assets': [{'id': f'pdf-page:{number}', 'locator': {'page': number}}],
        'coverage': {'visual_review_required': True},
        **extra,
    }


def original(units, count, **extra):
    return {
        'ok': True, 'format': 'pdf', 'status': 'partial', 'engine': 'builtin',
        'document_sha256': DIGEST, 'document': {'sha256': DIGEST, 'unit_count': count},
        'units': units, 'text': '\n\n'.join(row['text'] for row in units),
        'truncated': True, 'next_cursor': None, 'coverage': {}, 'warnings': [],
        **extra,
    }


def parsed(units):
    return {'ok': True, 'status': 'ready', 'source_sha256': DIGEST,
            'engine_version': 'synthetic-test-only', 'units': units, 'warnings': []}


class StructurePaginationTests(unittest.TestCase):
    def test_twelve_pages_and_long_page_fragments_match_normalized_text_exactly(self):
        expected, blocks = {}, []
        for number in range(1, 13):
            heading = f'STRUCTURED PHYSICAL PAGE {number:02d}'
            body = ('Normalized public β content ' * (65 if number in {3, 11} else 3)) + f'END {number}'
            expected[number] = heading + '\n\n' + body
            blocks.extend([
                {'locator': {'page': number}, 'text': heading, 'status': 'ready'},
                {'locator': {'page': number}, 'text': body, 'status': 'ready'},
            ])
        structured = parsed(blocks)
        # Construct without storage: every file/child/parser boundary is a
        # stub, while _execute's cursor adaptation and located_window are real.
        broker = object.__new__(jobs.DocumentJobs)
        broker.python = Path('D:/synthetic-python-never-launched.exe')
        calls = []

        def native_read(job_id, python, helper, request, timeout):
            calls.append(deepcopy(request))
            first = request.get('start_unit', 1)
            if len(calls) == 1:
                native = 'NATIVE PAGE ONE HAS A MUCH LONGER TEXT LAYER. ' * 40
                return original([original_page(1, native[:257], total_chars=len(native),
                                               truncated_unit=True)], 12,
                                next_cursor=jobs.reader.cursor_encode(DIGEST, 0, 257))
            self.assertNotIn('cursor', request)
            self.assertEqual(request['ocr'], 'off')
            self.assertEqual(request['max_chars'], 100000)
            return original([original_page(number, f'native {number}')
                             for number in range(first, min(13, first + 4))], 12)

        def upgrade(row, request, lightweight, *, required, engine='mineru'):
            self.assertTrue(required)
            return jobs.located_window(structured, request, lightweight, DESTINATION)

        reconstructed = {number: [] for number in range(1, 13)}
        ends = {number: 0 for number in range(1, 13)}
        hashes = {number: set() for number in range(1, 13)}
        positions, observed_pages = [], []
        token = None
        with patch.object(broker, '_source', return_value=None), \
                patch.object(broker, '_run_child', side_effect=native_read), \
                patch.object(broker, '_upgrade', side_effect=upgrade):
            for _ in range(100):
                request = {'root': 'D:/synthetic-authorized-root', 'path': 'synthetic.pdf',
                           'engine': 'mineru', 'max_chars': 257, 'max_units': 4}
                if token:
                    request['cursor'] = token
                result = broker._execute({'id': 'synthetic-job', 'source_hash': DIGEST,
                                          'request': json.dumps(request)})
                self.assertTrue(result['ok'], result)
                self.assertEqual(result['engine'], 'mineru')
                self.assertLessEqual(sum(len(row['text']) for row in result['units']), 257)
                self.assertLessEqual(len(result['units']), 4)
                for row in result['units']:
                    number = row['locator']['page']
                    self.assertEqual(row['unit_index'], number)
                    self.assertEqual(row['char_start'], ends[number])
                    self.assertEqual(row['total_chars'], len(expected[number]))
                    self.assertEqual(row['text'], expected[number][row['char_start']:row['char_end']])
                    self.assertEqual(row['assets'][0]['id'], f'pdf-page:{number}')
                    reconstructed[number].append(row['text'])
                    hashes[number].add(row['unit_text_sha256'])
                    ends[number] = row['char_end']
                    observed_pages.append(number)
                token = result['next_cursor']
                if token is None:
                    self.assertFalse(result['truncated'])
                    break
                self.assertTrue(result['truncated'])
                self.assertTrue(jobs.is_structured_cursor(token))
                position = jobs.reader.cursor_decode(token, DIGEST)
                if positions:
                    self.assertGreater(position, positions[-1])
                positions.append(position)
            else:
                self.fail('Structured pagination failed to terminate')
        self.assertEqual(sorted(set(observed_pages)), list(range(1, 13)))
        self.assertEqual(observed_pages, sorted(observed_pages))
        for number in range(1, 13):
            self.assertEqual(''.join(reconstructed[number]), expected[number])
            self.assertEqual(ends[number], len(expected[number]))
            self.assertEqual(hashes[number], {hashlib.sha256(expected[number].encode()).hexdigest()})
        self.assertGreater(len(reconstructed[3]), 4)
        self.assertGreater(len(reconstructed[11]), 4)
        # The structured first page is shorter than its native fragment. Its
        # next cursor must begin physical page two, not native character 257.
        self.assertEqual(positions[0], (1, 0))
        self.assertEqual(calls[1]['start_unit'], 2)

    def test_large_equation_and_table_metadata_cannot_bypass_text_budget(self):
        table = {'rows': [['STRUCTURAL_METADATA_' * 500]]}
        structured = parsed([{'locator': {'page': 1}, 'text': 'Short normalized page.',
                              'equations': [{'latex': 'x+' * 2000}], 'table': table}])
        source = original([original_page(1, table=table)], 1)
        result = jobs.located_window(structured, {'max_chars': 256}, source, DESTINATION)
        row = result['units'][0]
        self.assertEqual(row['text'], 'Short normalized page.')
        self.assertEqual(row['equations'], [])
        self.assertEqual(row['tables'], [])
        self.assertNotIn('table', row)
        self.assertNotIn('STRUCTURAL_METADATA_', json.dumps(result))
        self.assertEqual(row['coverage']['structured_content'], 'fragmented')
        self.assertFalse(result['truncated'])
        self.assertIsNone(result['next_cursor'])

    def test_unmapped_word_paragraph_keeps_builtin_text_cursor_and_assets_as_partial(self):
        word_row = {**original_page(1, 'Verified Word paragraph'),
                    'locator': {'paragraph': 1}, 'assets': [{'id': 'docx-image:1'}]}
        builtin_cursor = jobs.reader.cursor_encode(DIGEST, 0, 23)
        source = original([word_row], 4, format='docx', next_cursor=builtin_cursor)
        before = deepcopy(source)
        structured = parsed([{'locator': {'page': 1}, 'text': 'UNMAPPED REPLACEMENT'}])
        result = jobs.located_window(structured, {'max_chars': 256}, source, DESTINATION)
        self.assertTrue(result['ok'])
        self.assertEqual(result['engine'], 'builtin')
        self.assertEqual(result['structure_engine'], 'mineru')
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['units'], before['units'])
        self.assertEqual(result['text'], before['text'])
        self.assertEqual(result['next_cursor'], builtin_cursor)
        self.assertNotIn('UNMAPPED REPLACEMENT', result['text'])
        self.assertEqual(source, before)

    def test_native_pdf_visual_review_alone_does_not_request_structure_engine(self):
        base = original_page(1, 'Ordinary native PDF prose.')
        self.assertFalse(jobs.needs_structure(original([base], 1)))
        for extra in ({'extraction': 'ocr'}, {'extraction': 'text+ocr'},
                      {'status': 'needs_ocr'}, {'equations': [{'latex': 'x^2'}]},
                      {'table': {'rows': [['value']]}}, {'text': 'A formula contains ∫ x dx.'}):
            with self.subTest(extra=extra):
                self.assertTrue(jobs.needs_structure(original([{**base, **extra}], 1)))

    def test_structured_cursor_rejects_shortened_text_missing_mapping_or_changed_source(self):
        source = original([original_page(1)], 1)
        shortened = parsed([{'locator': {'page': 1}, 'text': 'Now too short.'}])
        seed = jobs.located_window(shortened, {'max_chars': 256},
                                   original([original_page(1)], 2), DESTINATION)
        request = {'cursor': cursor(0, 100, version_cursor=seed['next_cursor']), 'max_chars': 256}
        result = jobs.located_window(shortened, request, source, DESTINATION)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'], 'document_structure_cursor_invalid')
        missing = parsed([{'locator': {'page': 2}, 'text': 'Wrong physical page.'}])
        mapped_seed = jobs.located_window(missing, {'start_unit': 2, 'max_chars': 256},
                                          original([original_page(2)], 3), DESTINATION)
        missing_request = {'cursor': cursor(0, 100, version_cursor=mapped_seed['next_cursor']),
                           'max_chars': 256}
        result = jobs.located_window(missing, missing_request, source, DESTINATION)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'], 'document_structure_mapping_missing')
        changed_source = {**shortened, 'source_sha256': 'b' * 64}
        with self.assertRaises(jobs.reader.ReaderError) as caught:
            jobs.located_window(changed_source, request, source, DESTINATION)
        self.assertEqual(caught.exception.code, 'SOURCE_CHANGED')

    def test_same_source_same_length_replacement_rejects_old_normalized_text_version(self):
        source = original([original_page(1)], 1)
        original_text = 'Original normalized public text. ' * 40
        old = parsed([{'locator': {'page': 1}, 'text': original_text}])
        first = jobs.located_window(old, {'max_chars': 256}, source, DESTINATION)
        self.assertTrue(first['ok'])
        self.assertIsNotNone(first['next_cursor'])
        issued = json.loads(base64.urlsafe_b64decode(first['next_cursor']))
        self.assertEqual(issued['offset'], 256)
        self.assertRegex(issued['text_version'], r'^[0-9a-f]{64}$')
        request = {'cursor': first['next_cursor'], 'max_chars': 256}
        unchanged = jobs.located_window(deepcopy(old), request, source, DESTINATION)
        self.assertTrue(unchanged['ok'])
        self.assertEqual(unchanged['units'][0]['text'], original_text[256:512])

        replacement_text = original_text.replace('Original', 'Replaced')
        self.assertEqual(len(replacement_text), len(original_text))
        replacement = parsed([{'locator': {'page': 1}, 'text': replacement_text}])
        self.assertEqual(replacement['source_sha256'], old['source_sha256'])
        for changed in (
                replacement,
                parsed([{'locator': {'page': 1}, 'text': original_text[:100]}]),
                parsed([{'locator': {'page': 2}, 'text': original_text}])):
            with self.subTest(changed=changed['units'][0]['locator']):
                rejected = jobs.located_window(changed, request, source, DESTINATION)
                self.assertFalse(rejected['ok'])
                self.assertEqual(rejected['error']['code'], 'document_structure_changed')
                self.assertNotIn('units', rejected)
                self.assertNotIn('text', rejected)

        fresh = jobs.located_window(replacement, {'max_chars': 256}, source, DESTINATION)
        self.assertTrue(fresh['ok'])
        self.assertEqual(fresh['units'][0]['text'], replacement_text[:256])
        fresh_version = json.loads(base64.urlsafe_b64decode(fresh['next_cursor']))['text_version']
        self.assertNotEqual(fresh_version, issued['text_version'])

        # Legacy structured tokens lacking a version, and native character
        # offsets from another engine, cannot silently enter the new stream.
        legacy = jobs.located_window(old, {'cursor': cursor(0, 256)}, source, DESTINATION)
        self.assertEqual(legacy['error']['code'], 'document_structure_changed')
        native = jobs.located_window(old, {'cursor': jobs.reader.cursor_encode(DIGEST, 0, 256)},
                                     source, DESTINATION)
        self.assertEqual(native['error']['code'], 'document_cursor_engine_changed')


if __name__ == '__main__':
    unittest.main()
