"""Keyless local transport fixtures, not model or classroom generation tests."""
from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from integration.harness_bridge import HarnessError, HarnessTransport
from integration.workspace_management import WorkspaceManager


class FixtureTransport:
    def __init__(self):
        self.native = [{'workspace_id': 'native_one', 'display_name': 'Custom original',
            'kind': 'workspace', 'path': 'D:\\synthetic-folder', 'archived': False,
            'status': 'ready', 'resources': {'skills': ['preserved']}}]
        self.host_rows = [{'id': 'harness_one', 'path': 'D:\\synthetic-folder',
            'title': 'Old cached title', 'archived': False, 'session_ids': ['workspace-existing']}]
        self.reservations = {}
        self.calls = []
        self.faults = {}
        self.busy = False

    def fault(self, name):
        if self.faults.get(name, 0):
            self.faults[name] -= 1
            raise HarnessError('fixture_io_failure', 'Fixture save failure', 503)

    async def native_workspace_service(self, method, path='workspaces', body=None):
        self.calls.append(('native', method, path, deepcopy(body)))
        if method == 'GET':
            return {'workspaces': deepcopy(self.native)}
        row = next(row for row in self.native if row['workspace_id'] == path.rsplit('/', 1)[1])
        if body['expected'] != {'name': row['display_name'], 'archived': row['archived'],
                                'path': row['path'], 'kind': row['kind']}:
            raise HarnessError('workspace_revision_changed', 'Changed', 409)
        self.fault('native_before')
        if 'name' in body:
            row['display_name'] = body['name']
        if 'archived' in body:
            row['archived'] = body['archived']
        self.fault('native_after')
        return {'workspace': deepcopy(row)}

    async def host(self, method, path, body=None, timeout=45):
        self.calls.append(('host', method, path, deepcopy(body)))
        if path == '/workspaces':
            return {'workspaces': [{**deepcopy(row), 'management_blocked': row['id'] in self.reservations} for row in self.host_rows]}
        identity = path.split('/')[2]
        row = next(row for row in self.host_rows if row['id'] == identity)
        if path.endswith('/management'):
            self.fault('status')
            return {'workspace': deepcopy(row), 'reservation': deepcopy(self.reservations.get(identity))}
        if body['phase'] == 'prepare':
            if self.busy:
                raise HarnessError('workspace_busy', 'Busy', 409)
            if identity in self.reservations:
                raise HarnessError('workspace_recovery_required', 'Pending', 409)
            reservation = {'transaction_id': str(uuid.uuid4()), 'before': deepcopy(row),
                'patch': {key: body[key] for key in ('name', 'archived', 'native_workspace_id') if key in body},
                'native_before': deepcopy(body.get('native_before'))}
            self.reservations[identity] = reservation
            return {'workspace': deepcopy(row), 'reservation': deepcopy(reservation)}
        reservation = self.reservations.get(identity)
        if not reservation:
            if row.get('last_transaction_id') == body['transaction_id'] and body['phase'] == 'commit':
                return {'workspace': deepcopy(row), 'reservation': None}
            raise HarnessError('workspace_management_stale', 'Stale', 409)
        if reservation['transaction_id'] != body['transaction_id']:
            raise HarnessError('workspace_management_stale', 'Stale', 409)
        if body['phase'] == 'abort':
            del self.reservations[identity]
            return {'workspace': deepcopy(row), 'reservation': None}
        self.fault('commit_before')
        row.update(reservation['patch'])
        if 'name' in row:
            row['title'] = row['name']
        row['last_transaction_id'] = body['transaction_id']
        del self.reservations[identity]
        self.fault('commit_after')
        return {'workspace': deepcopy(row), 'reservation': None}


class WorkspaceManagementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.transport = FixtureTransport()
        self.manager = WorkspaceManager(self.transport)

    async def test_native_and_harness_identity_rename_archive_restore_preserve_resources_sessions(self):
        renamed = await self.manager.manage('native_one', {'name': 'Updated'})
        self.assertEqual(renamed['workspace']['harness_workspace_id'], 'harness_one')
        self.assertEqual(renamed['workspace']['native_workspace_id'], 'native_one')
        self.assertEqual(renamed['workspace']['title'], 'Updated')
        await self.manager.manage('harness_one', {'archived': True})
        self.assertTrue(self.transport.native[0]['archived'])
        self.assertTrue(self.transport.host_rows[0]['archived'])
        await self.manager.manage('native_one', {'archived': False})
        self.assertEqual(self.transport.native[0]['resources'], {'skills': ['preserved']})
        self.assertEqual(self.transport.host_rows[0]['session_ids'], ['workspace-existing'])
        self.assertEqual(self.transport.host_rows[0]['id'], 'harness_one')
        self.assertEqual(self.transport.native[0]['display_name'], 'Updated')

    async def test_native_only_management_never_creates_harness_workspace_or_session(self):
        self.transport.host_rows = []
        result = await self.manager.manage('native_one', {'archived': True})
        self.assertIsNone(result['workspace']['harness_workspace_id'])
        self.assertEqual(self.transport.host_rows, [])
        self.assertFalse(any(method == 'POST' for source, method, path, body in self.transport.calls if source == 'host'))

    async def test_system_general_and_unknown_ids_are_protected(self):
        for kind in ('system', 'general'):
            self.transport.native[0]['kind'] = kind
            with self.assertRaises(HarnessError) as caught:
                await self.manager.manage('native_one', {'archived': True})
            self.assertEqual(caught.exception.code, 'workspace_protected')
        with self.assertRaises(HarnessError) as caught:
            await self.manager.manage('missing', {'name': 'Rename'})
        self.assertEqual(caught.exception.status, 404)

    async def test_busy_harness_does_not_mutate_native(self):
        self.transport.busy = True
        with self.assertRaises(HarnessError) as caught:
            await self.manager.manage('native_one', {'archived': True})
        self.assertEqual(caught.exception.code, 'workspace_busy')
        self.assertFalse(self.transport.native[0]['archived'])
        self.assertEqual(self.transport.reservations, {})

    async def test_native_failure_aborts_reservation_without_changes(self):
        self.transport.faults['native_before'] = 1
        with self.assertRaises(HarnessError):
            await self.manager.manage('native_one', {'archived': True})
        self.assertEqual(self.transport.reservations, {})
        self.assertFalse(self.transport.native[0]['archived'])
        self.assertFalse(self.transport.host_rows[0]['archived'])

    async def test_lost_host_commit_reply_does_not_rollback_confirmed_commit(self):
        self.transport.faults['commit_after'] = 1
        result = await self.manager.manage('native_one', {'archived': True})
        self.assertTrue(result['workspace']['archived'])
        self.assertEqual(self.transport.reservations, {})
        self.assertFalse(any(body and body.get('phase') == 'abort' for source, method, path, body in self.transport.calls))

    async def test_uncertain_host_save_does_not_rollback_while_commit_may_be_in_flight(self):
        self.transport.faults['commit_before'] = 2
        with self.assertRaises(HarnessError) as caught:
            await self.manager.manage('native_one', {'name': 'Not saved'})
        self.assertEqual(caught.exception.code, 'workspace_recovery_required')
        self.assertEqual(self.transport.native[0]['display_name'], 'Not saved')
        self.assertIn('harness_one', self.transport.reservations)
        self.assertEqual(self.transport.host_rows[0]['title'], 'Old cached title')
        patches = [body for source, method, path, body in self.transport.calls if source == 'native' and method == 'PATCH']
        self.assertEqual(len(patches), 1)
        rows = (await WorkspaceManager(self.transport).catalog())['workspaces']
        self.assertEqual(rows[0]['name'], 'Not saved')
        self.assertFalse(rows[0]['management_blocked'])
        self.assertEqual(self.transport.host_rows[0]['title'], 'Not saved')

    async def test_lost_native_reply_reads_back_then_finishes_commit(self):
        self.transport.faults['native_after'] = 1
        result = await self.manager.manage('harness_one', {'name': 'Reply lost'})
        self.assertEqual(result['workspace']['name'], 'Reply lost')
        self.assertEqual(self.transport.reservations, {})

    async def test_pending_native_patch_finishes_after_manager_restart(self):
        prepared = await self.transport.host('POST', '/workspaces/harness_one/manage',
            {'phase': 'prepare', 'archived': True, 'native_workspace_id': 'native_one',
             'native_before': {'workspace_id': 'native_one', 'name': 'Custom original', 'archived': False, 'path': 'D:\\synthetic-folder', 'kind': 'workspace'}})
        self.transport.native[0]['archived'] = True
        reopened = WorkspaceManager(self.transport)
        rows = (await reopened.catalog())['workspaces']
        self.assertTrue(rows[0]['archived'])
        self.assertFalse(rows[0]['management_blocked'])
        self.assertEqual(self.transport.host_rows[0]['last_transaction_id'], prepared['reservation']['transaction_id'])

    async def test_changed_native_name_blocks_recovery_and_never_overwrites_newer_metadata(self):
        await self.transport.host('POST', '/workspaces/harness_one/manage',
            {'phase': 'prepare', 'name': 'Prepared', 'native_workspace_id': 'native_one',
             'native_before': {'workspace_id': 'native_one', 'name': 'Custom original', 'archived': False, 'path': 'D:\\synthetic-folder', 'kind': 'workspace'}})
        self.transport.native[0]['display_name'] = 'Changed elsewhere'
        rows = (await WorkspaceManager(self.transport).catalog())['workspaces']
        self.assertTrue(rows[0]['management_blocked'])
        self.assertEqual(self.transport.native[0]['display_name'], 'Changed elsewhere')
        with self.assertRaises(HarnessError) as caught:
            await self.manager.manage('native_one', {'archived': True})
        self.assertEqual(caught.exception.code, 'workspace_recovery_required')

    async def test_uncertain_host_status_keeps_durable_reservation(self):
        self.transport.faults.update(commit_before=1, status=1)
        with self.assertRaises(HarnessError) as caught:
            await self.manager.manage('native_one', {'archived': True})
        self.assertEqual(caught.exception.code, 'workspace_recovery_required')
        self.assertIn('harness_one', self.transport.reservations)

    async def test_directory_migration_or_kind_change_never_qualifies_as_recovery_match(self):
        for field, value in [('path', 'D:\\migrated-fixture'), ('kind', 'general')]:
            transport = FixtureTransport()
            await transport.host('POST', '/workspaces/harness_one/manage',
                {'phase': 'prepare', 'name': 'Prepared', 'native_workspace_id': 'native_one',
                 'native_before': {'workspace_id': 'native_one', 'name': 'Custom original',
                    'archived': False, 'path': 'D:\\synthetic-folder', 'kind': 'workspace'}})
            transport.native[0]['display_name'] = 'Prepared'
            transport.native[0][field] = value
            await WorkspaceManager(transport).catalog()
            self.assertIn('harness_one', transport.reservations)
            self.assertFalse(any(body and body.get('phase') in ('commit', 'abort')
                                 for source, method, path, body in transport.calls))

    async def test_fresh_native_identity_must_match_catalog_before_prepare(self):
        original = self.manager._catalog
        async def migrated_catalog(*args, **kwargs):
            result = await original(*args, **kwargs)
            self.transport.native[0]['path'] = 'D:\\moved-after-catalog'
            return result
        self.manager._catalog = migrated_catalog
        with self.assertRaises(HarnessError) as caught:
            await self.manager.manage('native_one', {'name': 'Stale choice'})
        self.assertEqual(caught.exception.code, 'workspace_revision_changed')
        self.assertEqual(self.transport.reservations, {})
        self.assertEqual(self.transport.native[0]['display_name'], 'Custom original')

    async def test_external_catalog_restore_is_authoritative_and_missing_disk_does_not_block_metadata(self):
        self.transport.host_rows[0]['archived'] = True
        self.transport.native[0]['status'] = 'unavailable'
        self.transport.native[0]['archived'] = False
        self.assertFalse((await self.manager.catalog())['workspaces'][0]['archived'])
        await self.manager.manage('native_one', {'name': 'Offline renamed'})
        self.assertEqual(self.transport.native[0]['display_name'], 'Offline renamed')


if __name__ == '__main__':
    unittest.main()
