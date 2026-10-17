"""Original-text pagination using the real ReadingStore, no model calls."""
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'upstream'/'DeepTutor'))
from deeptutor.reading.store import ReadingStore
from deeptutor.reading.service import render_units
from deeptutor.reading.models import ReadingError


class ReadingPaginationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='deepsteam-reading-review-')
        self.store=ReadingStore(self.temp.name)
        self.identifier='a'*64

    def tearDown(self):
        self.temp.cleanup()

    def install(self,units):
        return self.store.ingest_units(self.identifier,filename='synthetic.md',units=units,unit='section')

    def test_thirty_units_report_and_deliver_the_remaining_six(self):
        self.install([f'Exact source unit {n}' for n in range(1,31)])
        first=render_units(self.store,self.identifier,'1-30')
        self.assertEqual(len(first.locators),24);self.assertTrue(first.truncated)
        self.assertEqual(first.remaining_locators,tuple(range(25,31)))
        second=render_units(self.store,self.identifier,None,cursor=first.next_cursor)
        self.assertEqual(second.locators,tuple(range(25,31)));self.assertFalse(second.truncated)
        self.assertIn('Exact source unit 30',second.text)

    def test_long_unit_tail_is_reachable_without_loss_or_repeated_prefix(self):
        original='START '+('ab cd '*23000)+' END-OF-ORIGINAL'
        self.install([original])
        cursor=None;fragments=[];text=[]
        while True:
            row=render_units(self.store,self.identifier,'1' if cursor is None else None,cursor=cursor)
            fragments.extend(row.fragments);text.append(row.text)
            cursor=row.next_cursor
            if not cursor:break
        self.assertEqual(fragments[0]['char_start'],0)
        self.assertEqual(fragments[-1]['char_end'],len(original))
        self.assertTrue(all(a['char_end']==b['char_start'] for a,b in zip(fragments,fragments[1:])))
        self.assertIn('END-OF-ORIGINAL',text[-1]);self.assertNotIn('START ',text[-1])

    def test_cursor_rejects_new_revision_and_another_material(self):
        self.install(['x'*65000]);first=render_units(self.store,self.identifier,'1')
        self.install(['changed '+('x'*65000)])
        with self.assertRaises(ReadingError):render_units(self.store,self.identifier,None,cursor=first.next_cursor)
        self.store.ingest_units('b'*64,filename='other.md',units=['y'*65000],unit='section')
        with self.assertRaises(ReadingError):render_units(self.store,'b'*64,None,cursor=first.next_cursor)

    def test_registered_alias_rejects_changed_original_file(self):
        path=Path(self.temp.name)/'source.txt';path.write_text('original source',encoding='utf-8')
        manifest=self.store.ingest(path)
        self.assertIn(str(path.resolve()),self.store.registered_source_aliases(manifest.material_id))
        path.write_text('different source revision',encoding='utf-8')
        self.assertNotIn(str(path.resolve()),self.store.registered_source_aliases(manifest.material_id))


if __name__=='__main__':unittest.main(verbosity=2)
