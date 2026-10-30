"""Real bundled parsers must read generated files in deep Windows workspaces."""
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('contest_reader', SOURCE / 'scripts/workspace_document_reader.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


def fixture_path(path):
    # The fixture needs to be writable before the production fix exists.
    value = str(path)
    if os.name == 'nt' and not value.startswith('\\\\?\\'):
        return Path('\\\\?\\' + value)
    return path


class DocumentLongPathTests(unittest.TestCase):
    def setUp(self):
        if os.name != 'nt':
            raise RuntimeError('This release case requires a real Windows filesystem')
        self.temp = tempfile.TemporaryDirectory(prefix='DeepSteam reader ')
        self.root = Path(self.temp.name)
        self.relative = '/'.join(['outputs', 'chat', '\u4e2d\u6587 with spaces ' + 'a' * 55,
                                  'session-' + 'b' * 70, 'turn-' + 'c' * 70])
        self.directory = self.root.joinpath(*self.relative.split('/'))
        fixture_path(self.directory).mkdir(parents=True)
        self.marker = 'CONTEST-LONG-PATH-37'
        self.name = '\u8bfe\u5802\u8bb0\u5f55 sample'
        self.assertGreater(len(str(self.directory / (self.name + '.md'))), 300)

    def tearDown(self):
        target = fixture_path(self.root)
        self.assertEqual(self.root.parent, Path(tempfile.gettempdir()))
        shutil.rmtree(target)
        self.temp.cleanup()

    def put(self, suffix, data):
        fixture_path(self.directory / (self.name + suffix)).write_bytes(data)
        return self.relative + '/' + self.name + suffix

    def test_all_five_formats_are_readable_at_deep_chinese_paths(self):
        import pymupdf
        from docx import Document
        from openpyxl import Workbook
        from pptx import Presentation
        from pptx.util import Inches
        documents = {'.md': ('# ' + self.marker).encode('utf-8')}
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((30, 50), self.marker)
            documents['.pdf'] = pdf.tobytes()
        word = Document(); word.add_heading(self.marker, 1)
        stream = io.BytesIO(); word.save(stream); documents['.docx'] = stream.getvalue()
        book = Workbook(); book.active.append([self.marker, 37])
        stream = io.BytesIO(); book.save(stream); documents['.xlsx'] = stream.getvalue(); book.close()
        deck = Presentation(); slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1)).text = self.marker
        stream = io.BytesIO(); deck.save(stream); documents['.pptx'] = stream.getvalue()
        for suffix, content in documents.items():
            with self.subTest(format=suffix):
                relative = self.put(suffix, content)
                result = reader.handle_request({'root': str(self.root), 'path': relative, 'ocr': 'off'})
                self.assertTrue(result['ok'], result)
                self.assertIn(self.marker, result['text'])
                self.assertEqual(result['path'], relative)
                self.assertEqual(result['document_sha256'], hashlib.sha256(content).hexdigest())

    def test_long_workspace_root_and_extended_root_share_file_identity(self):
        relative = self.put('.md', self.marker.encode())
        for root in (self.directory, fixture_path(self.directory)):
            result = reader.handle_request({'root': str(root), 'path': Path(relative).name})
            self.assertTrue(result['ok'], result)
            self.assertIn(self.marker, result['text'])

    def test_deep_path_checks_still_reject_escape_reparse_and_changed_file(self):
        relative = self.put('.md', self.marker.encode())
        for invalid in ('../secret.txt', 'folder/../secret.md', 'notes.md:stream', 'C:/secret.md'):
            result = reader.handle_request({'root': str(self.root), 'path': invalid})
            self.assertEqual(result['error']['code'], 'PATH_OUTSIDE_WORKSPACE')
        class Junction:
            st_mode = 0o040755
            st_file_attributes = 0x400
        with patch.object(Path, 'lstat', return_value=Junction()):
            result = reader.handle_request({'root': str(self.root), 'path': relative})
            self.assertEqual(result['error']['code'], 'PATH_REPARSE_POINT')
        with patch.object(reader, '_opened_windows_path', return_value=Path('C:/different.md')):
            result = reader.handle_request({'root': str(self.root), 'path': relative})
            self.assertEqual(result['error']['code'], 'PATH_CHANGED')
        result = reader.handle_request({'root': str(self.root), 'path': relative, 'document_sha256': '0' * 64})
        self.assertEqual(result['error']['code'], 'SOURCE_CHANGED')


if __name__ == '__main__':
    unittest.main(verbosity=2)
