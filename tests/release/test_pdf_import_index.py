"""Importing a small scan must not wait for every page's OCR or lose the original."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pymupdf
from deeptutor.reading import ReadingStore
from deeptutor.reading.directory_commit import ReadingStorageBusy, journal_path


class PDFImportIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='DeepSteam PDF 中文 path ')
        self.root=Path(self.temp.name);self.source=self.root/'small scan.pdf'
        with pymupdf.open() as raster_source:
            p=raster_source.new_page(width=200,height=200);p.insert_text((20,40),'SOURCE MARKER 73')
            image=p.get_pixmap().tobytes('png')
        with pymupdf.open() as pdf:
            for n in range(5):pdf.new_page(width=200,height=200).insert_image(pymupdf.Rect(0,0,200,200),stream=image)
            pdf.set_toc([[1,'Last page',5]]);pdf.save(self.source)
        self.store=ReadingStore(self.root/'reading')

    def tearDown(self):self.temp.cleanup()

    def test_small_scan_import_indexes_all_pages_without_eager_extraction(self):
        self.assertLess(self.source.stat().st_size,32*1024*1024)
        with patch('deeptutor.reading.store.extract_material',side_effect=AssertionError('eager OCR at import')):
            manifest=self.store.ingest(self.source)
        self.assertEqual(manifest.extractor,'pdf-on-demand');self.assertEqual(manifest.unit_count,5)
        self.assertEqual(self.store.raw_path(manifest.material_id).read_bytes(),self.source.read_bytes())
        index=json.loads((self.store._dir(manifest.material_id)/'pdf-index.json').read_text('utf-8'))
        self.assertEqual(index['sha256'],hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(index['text_extraction'],'on_demand')
        self.assertEqual(index['semantic_completeness'],'not_guaranteed')
        self.assertEqual(self.store.outline(manifest.material_id)[0].locator,5)
        self.assertFalse((self.store._dir(manifest.material_id)/'units').exists())

    def test_reimport_preserves_existing_cached_page_and_user_record(self):
        manifest=self.store.ingest(self.source);directory=self.store._dir(manifest.material_id)
        note=directory/'annotations.json';note.write_text('[{"id":"keep-user-record"}]','utf-8')
        cached=directory/'units/0005.txt';cached.parent.mkdir();cached.write_text('already read page five','utf-8')
        again=ReadingStore(self.store.root).ingest(self.source)
        self.assertEqual(again.to_dict(),manifest.to_dict())
        self.assertEqual(note.read_text('utf-8'),'[{"id":"keep-user-record"}]')
        self.assertEqual(cached.read_text('utf-8'),'already read page five')

    def test_first_import_sharing_violation_has_recoverable_journal(self):
        original=Path.replace
        def locked(src,dst):
            if src.name.endswith('.staging'):raise PermissionError('injected Windows sharing violation')
            return original(src,dst)
        with patch.object(Path,'replace',locked),patch('deeptutor.services.file_io.time.sleep'):
            with self.assertRaises(ReadingStorageBusy):self.store.ingest(self.source)
        mid=hashlib.sha256(self.source.read_bytes()).hexdigest()[:16]
        self.assertTrue(journal_path(self.store._dir(mid)).exists())
        reopened=ReadingStore(self.store.root).ingest(self.source)
        self.assertEqual(reopened.unit_count,5)
        self.assertEqual(self.store.raw_path(mid).read_bytes(),self.source.read_bytes())
        self.assertFalse(journal_path(self.store._dir(mid)).exists())

    def test_browser_view_preserves_original_pages_and_reuses_cache(self):
        manifest=self.store.ingest(self.source)
        raw=self.store.raw_path(manifest.material_id)
        original=hashlib.sha256(raw.read_bytes()).hexdigest()
        view_path=self.store.render_path(manifest.material_id)
        self.assertNotEqual(view_path,raw)
        with pymupdf.open(raw) as source,pymupdf.open(view_path) as view:
            self.assertEqual(len(source),len(view));self.assertEqual(source.get_toc(),view.get_toc())
            for index in range(len(source)):
                self.assertEqual(source[index].get_pixmap().samples,view[index].get_pixmap().samples)
                self.assertEqual(source[index].read_contents(),view[index].read_contents())
        self.assertEqual(hashlib.sha256(raw.read_bytes()).hexdigest(),original)
        before=view_path.stat().st_mtime_ns
        self.assertEqual(ReadingStore(self.store.root).render_path(manifest.material_id),view_path)
        self.assertEqual(view_path.stat().st_mtime_ns,before)


if __name__=='__main__':unittest.main(verbosity=2)
