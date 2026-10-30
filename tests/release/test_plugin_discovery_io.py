"""Installed wheel discovery must not stat every bundled dependency file."""
import csv
from importlib.metadata import PackagePath, PathDistribution
import io
import json
from pathlib import Path
import tempfile
import unittest

from deeptutor.plugins.registry import _manifest_files


class RecordDistribution:
    def __init__(self, root, paths):
        self.root = root
        self.paths = paths
        self.located = []

    def read_text(self, name):
        if name != 'RECORD': return None
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerows((path, '', '') for path in self.paths)
        return output.getvalue()

    @property
    def files(self):
        raise AssertionError('Full distribution file inventory was enumerated')

    def locate_file(self, path):
        self.located.append(str(path))
        return self.root / path


class PluginDiscoveryIOTests(unittest.TestCase):
    def test_large_wheel_without_plugin_never_probes_individual_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = RecordDistribution(Path(tmp), [f'package/data/{i}.bin' for i in range(10000)])
            self.assertEqual(_manifest_files(dist), [])
            self.assertEqual(dist.located, [])

    def test_only_manifest_is_read_with_csv_quoted_unicode_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            relative = '插件, with space/DeepTutor.Plugin.JSON'
            path = root / relative
            path.parent.mkdir()
            path.write_text('{"id":"example"}', encoding='utf-8')
            dist = RecordDistribution(root, ['unrelated/large.bin', relative])
            self.assertEqual(_manifest_files(dist), [(path, {'id': 'example'}, '')])
            self.assertEqual(dist.located, [relative])

    def test_manifest_updates_and_removal_are_not_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root / 'deeptutor.plugin.json'
            dist = RecordDistribution(root, [path.name])
            path.write_text('{"permissions":[]}', encoding='utf-8')
            self.assertEqual(_manifest_files(dist)[0][1]['permissions'], [])
            path.write_text('{"permissions":["shell"]}', encoding='utf-8')
            self.assertEqual(_manifest_files(dist)[0][1]['permissions'], ['shell'])
            path.unlink()
            self.assertEqual(_manifest_files(dist), [])

    def test_invalid_json_remains_a_broken_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root / 'deeptutor.plugin.json'
            path.write_text('{broken', encoding='utf-8')
            rows = _manifest_files(RecordDistribution(root, [path.name]))
            self.assertEqual(rows[0][0], path)
            self.assertIsNone(rows[0][1])
            self.assertTrue(rows[0][2])

    def test_real_distribution_and_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); info = root / 'sample.dist-info'; info.mkdir()
            path = root / 'deeptutor.plugin.json'
            path.write_text('{"id":"live"}', encoding='utf-8')
            (info / 'RECORD').write_text('deeptutor.plugin.json,,\nmissing.bin,,\n', encoding='utf-8')
            self.assertEqual(_manifest_files(PathDistribution(info)), [(path, {'id': 'live'}, '')])
            class Legacy:
                files = [PackagePath('deeptutor.plugin.json')]
                def locate_file(self, item): return root / item
            self.assertEqual(_manifest_files(Legacy()), [(path, {'id': 'live'}, '')])


if __name__ == '__main__': unittest.main(verbosity=2)
