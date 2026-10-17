"""Real process-death regressions, using only temporary application copies."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(os.environ.get('REPAIR_TEST_SOURCE', Path(__file__).resolve().parents[2] / 'scripts' / 'repair_bundle.py'))


def load(app, store):
    spec = importlib.util.spec_from_file_location('repair_under_test', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.APP, module.STORE = Path(app), Path(store)
    return module


def crash_helper():
    app, store, target, identifier, action, count = sys.argv[2:]
    module = load(app, store)
    root = Path(target).resolve()
    original_replace, original_unlink = os.replace, Path.unlink
    calls = 0

    def tick(path):
        nonlocal calls
        path = Path(str(path).removeprefix('\\\\?\\'))
        if Path(path).resolve().is_relative_to(root):
            calls += 1
            if calls == int(count):
                os._exit(77)

    def replace(source, destination):
        original_replace(source, destination)
        tick(destination)

    def unlink(path, *args, **kwargs):
        result = original_unlink(path, *args, **kwargs)
        tick(path)
        return result

    os.replace, Path.unlink = replace, unlink
    module.run({'action': action, 'id': identifier})
    raise AssertionError('Expected process death was not reached')


class RepairTests(unittest.TestCase):
    def test_complete_credential_fields_in_success_failure_and_commands(self):
        for success in (True, False):
            identifier=self.stage()
            samples=['Cookie: a=SYNTHETIC_FIRST; login=SYNTHETIC_SECOND',
                'cookie:a=SYNTHETIC_FIRST;login=SYNTHETIC_SECOND',
                'Set-Cookie: a=SYNTHETIC_FIRST; Path=/; login=SYNTHETIC_SECOND',
                'Authorization: Basic SYNTHETIC_SECOND',
                json.dumps({'headers':{'Cookie':'a=SYNTHETIC_FIRST; login=SYNTHETIC_SECOND'}})]
            code='import sys; print('+repr('\n'.join(samples))+'); print('+repr(samples[0])+',file=sys.stderr); sys.exit('+str(0 if success else 2)+')'
            self.module.run({'action':'verify','id':identifier,'command':[sys.executable,'-c',code,'--cookie','a=SYNTHETIC_FIRST;login=SYNTHETIC_SECOND']})
            receipt=(self.store/identifier/'manifest.json').read_text('utf-8')
            self.assertNotIn('SYNTHETIC_FIRST',receipt);self.assertNotIn('SYNTHETIC_SECOND',receipt)
        self.assertEqual(self.module.redact({'headers':{'Set-Cookie':['a=SYNTHETIC_FIRST','b=SYNTHETIC_SECOND']}}),{'headers':{'Set-Cookie':'[redacted]'}})

    @unittest.skipUnless(os.name == 'nt', 'Windows temporary suffix exceeds MAX_PATH')
    def test_atomic_temporary_suffix_crosses_windows_path_limit(self):
        target = self.copy / ('a' * 70) / ('b' * 70) / '中文 交付文件.md'
        while len(str(target)) < 250:
            target = target.with_name('c' + target.name)
        self.assertGreater(len(str(target)) + 37, 260)
        self.module.atomic(target, b'first delivery')
        self.module.atomic(target, b'replaced delivery')
        self.assertEqual(target.read_bytes(), b'replaced delivery')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='deepsteam-repair-regression-')
        self.root = Path(self.temp.name)
        self.app = self.root / 'app'
        self.copy = self.root / 'isolated copy'
        self.app.mkdir(); self.copy.mkdir()
        self.store = self.root / 'repairs'
        self.module = load(self.app, self.store)

    def tearDown(self):
        self.temp.cleanup()

    def stage(self, target=None):
        target = target or self.copy
        target.mkdir(parents=True, exist_ok=True)
        (target / 'a.py').write_text('VALUE = 1\n', encoding='utf-8')
        (target / 'b.json').write_text('{"value": 1}', encoding='utf-8')
        record = self.module.run({'action': 'stage', 'target_root': str(target), 'files': [
            {'path': 'a.py', 'content': 'VALUE = 2\n'},
            {'path': 'b.json', 'content': '{"value": 2}'},
            {'path': 'new.txt', 'content': 'new content'}]})
        identifier = record['id']
        self.module.run({'action': 'verify', 'id': identifier,
            'command': [sys.executable, '-c', "from pathlib import Path; assert 'VALUE = 2' in Path('a.py').read_text()"]})
        return identifier

    def test_live_root_subdirectory_and_parent_are_queued(self):
        for target in (self.app, self.app / 'integration'):
            identifier = self.stage(target)
            result = self.module.run({'action': 'apply', 'id': identifier, '_offline': True})
            self.assertEqual(result['status'], 'queued_for_restart')
            self.assertEqual((target / 'a.py').read_text(), 'VALUE = 1\n')
        record = self.module.run({'action': 'stage', 'target_root': str(self.root),
            'files': [{'path': 'app/integration/a.py', 'content': 'VALUE = 3'}]})
        self.module.run({'action': 'verify', 'id': record['id'], 'command': [sys.executable, '-c', 'pass']})
        self.assertEqual(self.module.run({'action': 'apply', 'id': record['id']})['status'], 'queued_for_restart')

    def test_checked_command_does_not_claim_behavior_and_redacts_success(self):
        identifier = self.stage()
        secret = 'sk-' + ('synthetic' * 4)
        result = self.module.run({'action': 'verify', 'id': identifier,
            'command': [sys.executable, '-c', f"print('{secret}'); print('token=syntheticTestValue')"]})
        self.assertEqual(result['validation']['behavior_fix'], 'not_established')
        receipt = (self.store / identifier / 'manifest.json').read_text('utf-8')
        self.assertNotIn(secret, receipt)
        self.assertNotIn('syntheticTestValue', receipt)

    def test_unrelated_edit_is_not_overwritten(self):
        identifier = self.stage()
        (self.copy / 'b.json').write_text('{"someone_else":true}')
        with self.assertRaises(ValueError):
            self.module.run({'action': 'apply', 'id': identifier})
        self.assertEqual((self.copy / 'a.py').read_text(), 'VALUE = 1\n')

    def test_process_death_at_every_apply_and_rollback_write(self):
        for direction in ('apply', 'rollback'):
            for point in range(1, 4):
                with self.subTest(direction=direction, point=point):
                    target = self.copy / f'{direction}-{point}'
                    identifier = self.stage(target)
                    if direction == 'rollback':
                        self.module.run({'action': 'apply', 'id': identifier})
                    result = subprocess.run([sys.executable, __file__, '--crash-helper', str(self.app),
                        str(self.store), str(target), identifier, direction, str(point)], capture_output=True,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    self.assertEqual(result.returncode, 77, result.stderr.decode(errors='replace'))
                    final = self.module.run({'action': direction, 'id': identifier})
                    self.assertEqual(final['status'], 'applied' if direction == 'apply' else 'rolled_back')
                    self.assertEqual((target / 'a.py').read_text(), 'VALUE = 2\n' if direction == 'apply' else 'VALUE = 1\n')
                    self.assertEqual((target / 'new.txt').exists(), direction == 'apply')
                    # A completed operation is also safely repeatable.
                    self.module.run({'action': direction, 'id': identifier})

    def test_partial_apply_can_be_rolled_back(self):
        identifier = self.stage()
        result = subprocess.run([sys.executable, __file__, '--crash-helper', str(self.app), str(self.store),
            str(self.copy), identifier, 'apply', '1'], capture_output=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 77)
        self.module.run({'action': 'rollback', 'id': identifier})
        self.assertEqual((self.copy / 'a.py').read_text(), 'VALUE = 1\n')
        self.assertFalse((self.copy / 'new.txt').exists())


if __name__ == '__main__':
    if '--crash-helper' in sys.argv:
        crash_helper()
    else:
        unittest.main(verbosity=2)
