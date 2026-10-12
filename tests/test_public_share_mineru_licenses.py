"""MinerU public-license selection fixtures; no installed state or release ZIPs.

The subject's build dependencies, upstream Git access and broad source walks
are replaced with fixtures. Only temporary license files are read or changed.
"""
from __future__ import annotations

import hashlib
import importlib.util
from importlib.machinery import ModuleSpec
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


PROJECT = Path(__file__).resolve().parents[1]
SUBJECT_PATH = PROJECT / 'reports/prepare_r6_models_share.py'


def load_plain_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# This helper module defines functions/constants only at import time. Reuse its
# actual path validator rather than replacing path safety with a permissive mock.
HELPERS = load_plain_module('mineru_license_fixture_zip_helpers', PROJECT / 'installer/build_r4_candidate.py')
RETIRED = load_plain_module('public_share_retired_component_rules', PROJECT / 'installer/retired_components.py')


class FixtureLoader:
    def __init__(self, values):
        self.values = values

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        module.__dict__.update(vars(self.values))


class PublicShareMineruLicenseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='public-mineru-license-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'public-source'
        self.root.mkdir()
        for name in ('portal', 'integration', 'scripts', 'tests', 'demo', 'desktop', 'licenses', 'reports'):
            (self.root / name).mkdir()
        self.walked = []
        self.packager = SimpleNamespace(
            ROOT_FILES=(), INSTALLER_SOURCES=(), HARNESS_INSTALLER_SOURCES=(),
            SKIP_DIRS=set(), SKIP_SUFFIXES=set(), TEXT_SUFFIXES={'.txt', '.md'},
            SECRET_PATTERNS={}, allowed=lambda value: True,
            git=MagicMock(side_effect=self.git_fixture),
        )
        self.boundary = SimpleNamespace(
            SKIP_SOURCE_DIRECTORIES=set(), SKIP_SOURCE_SUFFIXES=set(), SKIP_SOURCE_FILES=set(),
            walk_public_sources=self.walk_fixture,
        )
        self.release = SimpleNamespace(h=HELPERS, VERSION='fixture-only', ARTIFACT=self.root / 'fixture-artifact')
        fixtures = {
            'r6_release_package': self.release,
            'r6_clean_source_rules': SimpleNamespace(packager=self.packager),
            'r6_source_boundaries': self.boundary,
            'r6_retired_components': RETIRED,
        }
        spec = importlib.util.spec_from_file_location('public_share_mineru_license_subject', SUBJECT_PATH)
        self.subject = importlib.util.module_from_spec(spec)

        def fixture_spec(name, location, *args, **kwargs):
            if name not in fixtures:
                raise AssertionError('Unexpected external module import: ' + name)
            return ModuleSpec(name, FixtureLoader(fixtures[name]))

        with patch.object(importlib.util, 'spec_from_file_location', side_effect=fixture_spec):
            spec.loader.exec_module(self.subject)
        self.subject.ROOT = self.root
        self.subject.MINERU_LICENSE_ROWS.clear()
        self.source = self.root / 'reports/reviewed-license/MINERU-LICENSE.txt'
        self.source.parent.mkdir()
        self.blob = b'Original license fixture\n'
        self.source.write_bytes(self.blob)
        self.target = 'licenses/mineru/MINERU-LICENSE.txt'
        self.row = {'source': str(self.source), 'target': self.target, 'bytes': len(self.blob),
                    'sha256': hashlib.sha256(self.blob).hexdigest()}
        self.manifest = self.root / self.subject.MINERU_LICENSE_MANIFEST
        self.write_manifest()

    @staticmethod
    def git_fixture(repo, *args):
        if args[0] == 'ls-files':
            return b''
        if args[0] in ('rev-parse', 'describe'):
            return b'fixture-public-source\n'
        raise AssertionError('Unexpected Git operation: ' + repr(args))

    def walk_fixture(self, directory):
        directory = Path(directory)
        self.walked.append(directory)
        historical = self.root / 'licenses/mineru'
        if directory == self.root / 'licenses' or directory.is_relative_to(historical):
            raise AssertionError('The historical MinerU license tree must never be walked')
        return sorted(path for path in directory.rglob('*') if path.is_file()) if directory.exists() else []

    def write_manifest(self, rows=None, **changes):
        value = {'schema': 'deepsteam-mineru-runtime-v1', 'engine_version': '4.0.12',
                 'tool_only': True, 'redistribution_status': 'verified',
                 'files': [dict(self.row)] if rows is None else rows}
        value.update(changes)
        self.manifest.write_text(json.dumps(value), encoding='utf8')

    def test_source_files_skips_historical_tree_and_keeps_unlisted_files_on_disk(self):
        historical = self.root / 'licenses/mineru'
        old = historical / 'old-evidence/UNLISTED.txt'
        old.parent.mkdir(parents=True)
        old.write_bytes(b'Historical evidence must remain on disk only.\n')
        self.source = historical / 'reviewed-final/MINERU-LICENSE.txt'
        self.source.parent.mkdir()
        self.source.write_bytes(self.blob)
        self.row['source'] = str(self.source)
        # A full component manifest also contains runtime rows. Their source
        # files need not be opened when selecting only license targets.
        self.write_manifest(rows=[dict(self.row), {
            'source': str(self.base / 'missing-runtime-must-not-be-read.dat'),
            'target': 'runtime/mineru/not-a-license.dat', 'bytes': 0, 'sha256': '0' * 64,
        }])
        other = self.root / 'licenses/other/LICENSE.txt'
        other.parent.mkdir()
        other.write_bytes(b'Other public license fixture\n')
        original_iterdir, original_read = Path.iterdir, Path.read_bytes

        def guarded_iterdir(path):
            if path.is_relative_to(historical):
                raise AssertionError('Historical license directory was enumerated')
            return original_iterdir(path)

        def guarded_read(path):
            if path.is_relative_to(historical) and path != self.source:
                raise AssertionError('Historical license bytes were read')
            return original_read(path)

        with patch.object(Path, 'iterdir', new=guarded_iterdir), patch.object(Path, 'read_bytes', new=guarded_read):
            selected, versions = self.subject.source_files()
        self.assertEqual(selected[self.target], self.source)
        self.assertIn('licenses/other/LICENSE.txt', selected)
        self.assertNotIn('licenses/mineru/old-evidence/UNLISTED.txt', selected)
        self.assertNotIn('runtime/mineru/not-a-license.dat', selected)
        self.assertEqual(old.read_bytes(), b'Historical evidence must remain on disk only.\n')
        self.assertEqual(set(versions), {'DeepTutor', 'OpenMAIC', 'DeepSeekHarness'})
        self.assertEqual(self.packager.git.call_count, 9)
        self.assertFalse(any(path.is_relative_to(historical) for path in self.walked))

    def test_missing_unverified_or_wrong_component_contract_is_rejected(self):
        self.manifest.unlink()
        with self.assertRaises(FileNotFoundError):
            self.subject.mineru_license_sources()
        for changes in (
            {'redistribution_status': 'pending'}, {'redistribution_status': None},
            {'schema': 'unreviewed-component'}, {'engine_version': '4.0.11'},
            {'tool_only': False}, {'tool_only': 1}, {'files': []},
        ):
            with self.subTest(changes=changes):
                self.write_manifest(**changes)
                with self.assertRaises(RuntimeError):
                    self.subject.mineru_license_sources()
                self.assertEqual(self.subject.MINERU_LICENSE_ROWS, {})

    def test_length_hash_and_same_length_source_changes_are_rejected(self):
        for change in ({'bytes': len(self.blob) + 1}, {'sha256': '0' * 64}):
            with self.subTest(change=change):
                self.write_manifest(rows=[dict(self.row, **change)])
                with self.assertRaisesRegex(RuntimeError, 'license changed'):
                    self.subject.mineru_license_sources()
        self.write_manifest()
        self.source.write_bytes(self.blob.replace(b'Original', b'Modified'))
        self.assertEqual(self.source.stat().st_size, self.row['bytes'])
        with self.assertRaisesRegex(RuntimeError, 'license changed'):
            self.subject.mineru_license_sources()

    def test_duplicate_targets_are_rejected_case_insensitively(self):
        for target in (self.target, self.target.lower()):
            with self.subTest(target=target):
                self.write_manifest(rows=[dict(self.row), dict(self.row, target=target)])
                with self.assertRaisesRegex(RuntimeError, 'duplicate'):
                    self.subject.mineru_license_sources()
                self.assertEqual(self.subject.MINERU_LICENSE_ROWS, {})

    def test_target_traversal_and_absolute_or_relative_source_escape_are_rejected(self):
        outside = self.base / 'outside-license.txt'
        outside.write_bytes(self.blob)
        bad_rows = [dict(self.row, target=value) for value in (
            'licenses/mineru/../outside.txt', 'licenses/mineru//LICENSE.txt',
            'licenses/mineru/C:/outside.txt', 'licenses/mineru/..\\outside.txt')]
        bad_rows.extend((dict(self.row, source=str(outside)), dict(self.row, source='../outside-license.txt')))
        for row in bad_rows:
            with self.subTest(row=row):
                self.write_manifest(rows=[row])
                with self.assertRaises(RuntimeError):
                    self.subject.mineru_license_sources()
        self.assertEqual(outside.read_bytes(), self.blob)

    def test_leaf_and_ancestor_reparse_points_are_rejected_without_real_links(self):
        original_lstat = Path.lstat
        for bad_path in (self.source, self.source.parent):
            with self.subTest(kind='reparse-attribute', path=bad_path):
                def reparse_stat(path, *args, **kwargs):
                    attributes = original_lstat(path, *args, **kwargs)
                    if path == bad_path:
                        return SimpleNamespace(st_mode=attributes.st_mode,
                                               st_file_attributes=getattr(attributes, 'st_file_attributes', 0) | 0x400)
                    return attributes

                with patch.object(Path, 'lstat', new=reparse_stat):
                    with self.assertRaisesRegex(RuntimeError, 'reparse'):
                        self.subject.mineru_license_sources()
        for method, bad_path in (('is_symlink', self.source), ('is_junction', self.source.parent)):
            original = getattr(Path, method)
            with self.subTest(kind=method), patch.object(Path, method, new=lambda path: path == bad_path or original(path)):
                with self.assertRaisesRegex(RuntimeError, 'reparse'):
                    self.subject.mineru_license_sources()

    def test_read_gate_accepts_listed_license_and_rejects_unlisted_existing_license(self):
        selected = self.subject.mineru_license_sources()
        self.assertEqual(self.subject.checked_public_source(self.target, selected[self.target]), self.blob)
        unlisted = self.root / 'licenses/mineru/OLD-NOTICE.txt'
        unlisted.parent.mkdir(parents=True)
        unlisted.write_bytes(b'Unlisted historical notice\n')
        with self.assertRaisesRegex(RuntimeError, 'not covered'):
            self.subject.checked_public_source('licenses/mineru/OLD-NOTICE.txt', unlisted)
        self.assertTrue(unlisted.is_file())

    def test_changed_frozen_license_is_rejected_before_any_zip_entry_is_written(self):
        selected = self.subject.mineru_license_sources()
        self.source.write_bytes(self.blob.replace(b'Original', b'Modified'))
        archive = MagicMock()
        archive.__enter__.return_value = archive
        output = self.root / 'fixture-must-not-be-created.zip'
        with patch.object(self.subject.zipfile, 'ZipFile', return_value=archive) as open_zip:
            with self.assertRaisesRegex(RuntimeError, 'not covered'):
                self.subject.build_zip(output, selected, {})
        open_zip.assert_called_once()
        archive.writestr.assert_not_called()
        self.assertFalse(output.exists())

    def test_exact_retired_paths_are_rejected_at_read_gate_without_brand_filtering(self):
        retired_names = [prefix + 'historical.txt' for prefix in RETIRED.RETIRED_PREFIXES]
        retired_names.extend(RETIRED.RETIRED_FILES)
        for name in retired_names:
            source = self.root / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b'Historical product-owned source\n')
            for variant in (name, name.upper(), name.replace('/', '\\')):
                with self.subTest(name=variant):
                    self.assertFalse(self.subject.allowed(Path(variant)))
                    with self.assertRaisesRegex(RuntimeError, 'Not a distributable|Unsafe payload-relative path'):
                        self.subject.checked_public_source(variant, source)
            self.assertTrue(source.is_file())
        for name in ('licenses/Qwen-Apache-2.0.txt', 'integration/local_qwen_alternative/README.md',
                     'integration/my_qwen_api.py', 'runtime/mineru/model-assets/qwen.txt',
                     'upstream/DeepSeekHarness/integration/local_qwen/README.md'):
            with self.subTest(preserved=name):
                self.assertTrue(self.subject.allowed(Path(name)))

    def test_source_selection_excludes_all_owned_retired_paths_and_keeps_other_models(self):
        retired_names = [prefix + 'historical.txt' for prefix in RETIRED.RETIRED_PREFIXES]
        retired_names.extend(RETIRED.RETIRED_FILES)
        for name in retired_names:
            source = self.root / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b'Retired source fixture remains on disk\n')
        # Also exercise the non-walked explicit root allowlist.
        self.packager.ROOT_FILES = ('models/local-qwen/historical.txt',)
        preserved = ('licenses/Qwen-Apache-2.0.txt', 'integration/local_qwen_alternative/README.md',
                     'integration/my_qwen_api.py')
        for name in preserved:
            source = self.root / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b'Independent public source fixture\n')
        upstream_name = 'integration/local_qwen/upstream-reference.txt'
        upstream = self.root / 'upstream/DeepSeekHarness' / upstream_name
        upstream.parent.mkdir(parents=True)
        upstream.write_bytes(b'Upstream reference has separate ownership\n')
        original_git = self.git_fixture

        def source_git(repo, *args):
            if args[0] == 'ls-files' and Path(repo).name == 'DeepSeekHarness':
                return (upstream_name + '\0').encode('utf8')
            return original_git(repo, *args)

        self.packager.git.side_effect = source_git
        selected, _ = self.subject.source_files()
        self.assertFalse(any(RETIRED.retired_program_path(name) for name in selected))
        for name in retired_names:
            self.assertNotIn(name, selected)
            self.assertTrue((self.root / name).is_file())
        for name in preserved:
            self.assertIn(name, selected)
        self.assertIn('upstream/DeepSeekHarness/' + upstream_name, selected)
        self.assertIn(self.target, selected)


if __name__ == '__main__':
    unittest.main(verbosity=2)
