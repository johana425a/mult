import tempfile
import unittest
from pathlib import Path

from integration.workspace_document_inventory import InventoryStore, _iterators


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.workspace = self.base / 'workspace'
        self.workspace.mkdir()
        self.state = self.base / 'state'
        self.store = InventoryStore(self.state)

    def tearDown(self):
        for key in list(_iterators):
            if key[0].startswith(str(self.base)):
                _iterators.pop(key)[1].close()
        self.temporary.cleanup()

    def all_pages(self, store=None, **first):
        store = store or self.store
        rows, payload = [], dict(first)
        for _ in range(100):
            result = store.page(self.workspace, payload)
            self.assertTrue(result['ok'], result)
            self.assertFalse(result['reading_complete'])
            self.assertLessEqual(len(result['entries']), 200)
            rows.extend(result['entries'])
            if result['next_cursor'] is None:
                self.assertTrue(result['catalog_complete'])
                return rows, result
            payload = {'cursor': result['next_cursor'], 'path': first.get('path', '.')}
        self.fail('inventory did not finish')

    def test_large_tree_is_complete_and_durable(self):
        for n in range(723):
            directory = self.workspace / str(n % 9)
            directory.mkdir(exist_ok=True)
            (directory / ('material%d.md' % n)).write_text('Body text', encoding='utf8')
        first = self.store.page(self.workspace, {'limit': 71})
        self.assertFalse(first['catalog_complete'])
        # Emulate process exit: no in-memory directory iterator survives.
        for key in list(_iterators):
            _iterators.pop(key)[1].close()
        rows, end = self.all_pages(InventoryStore(self.state), cursor=first['next_cursor'])
        rows = first['entries'] + rows
        self.assertEqual(len(rows), 723)
        self.assertEqual(len({row['path'] for row in rows}), 723)
        self.assertEqual(end['total_discovered'], 723)

    def test_refresh_versions_and_old_snapshot(self):
        (self.workspace / 'a.md').write_text('one')
        rows, old = self.all_pages()
        (self.workspace / 'b.pdf').write_bytes(b'pdf')
        unchanged, _ = self.all_pages()
        self.assertEqual(len(unchanged), 1)
        current, new = self.all_pages(refresh=True)
        self.assertEqual(len(current), 2)
        self.assertNotEqual(old['inventory_id'], new['inventory_id'])

    def test_scope_tamper_traversal_and_private_directory(self):
        (self.workspace / '.ssh').mkdir()
        (self.workspace / '.ssh' / 'id_rsa').write_text('do not index')
        (self.workspace / 'ordinary.bin').write_bytes(b'abc')
        rows, result = self.all_pages()
        self.assertEqual([r['path'] for r in rows], ['ordinary.bin'])
        self.assertFalse(rows[0]['supported'])
        self.assertEqual(result['skipped_entries'], 1)
        self.assertFalse(self.store.page(self.workspace, {'path': '../state'})['ok'])
        self.assertFalse(self.store.page(self.workspace, {'path': '.ssh'})['ok'])
        for n in range(301):
            (self.workspace / ('%d.txt' % n)).write_text('x')
        cursor = self.store.page(self.workspace, {'refresh': True})['next_cursor']
        self.assertFalse(self.store.page(self.workspace, {'cursor': cursor[:-2] + 'xx'})['ok'])
        other = self.base / 'other'
        other.mkdir()
        self.assertFalse(self.store.page(other, {'cursor': cursor})['ok'])

    def test_empty_and_subdirectory(self):
        rows, result = self.all_pages()
        self.assertEqual(rows, [])
        self.assertEqual(result['status'], 'ready')
        sub = self.workspace / 'sub'
        sub.mkdir()
        (sub / 'note.txt').write_text('x')
        rows, _ = self.all_pages(path='sub')
        self.assertEqual(rows[0]['path'], 'sub/note.txt')


if __name__ == '__main__':
    unittest.main()
