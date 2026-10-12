"""Coordinated reversible workspace metadata changes; no file or session deletion.

The Host durably reserves projects while native metadata changes. Commit IDs
make lost HTTP replies distinguishable from failed saves. A later catalog read
finishes interrupted transactions only when native metadata still matches.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import os
import re

from integration.harness_bridge import HarnessError


def path_key(value):
    # Registered paths are already canonical. Do not require an attached disk
    # just to rename/archive its registration or read retained history.
    return os.path.normcase(os.path.normpath(str(value or '')))


def native_row(row):
    return {'workspace_id': row['workspace_id'], 'name': row.get('display_name', row.get('name', '')),
            'path': row.get('path', ''), 'kind': row.get('kind', 'workspace'),
            'archived': bool(row.get('archived')), 'status': row.get('status', 'ready')}


def snapshot(row):
    return {key: row[key] for key in ('workspace_id', 'name', 'archived', 'path', 'kind')}


def metadata_equal(row, expected):
    return (row is not None and expected is not None
            and row.get('workspace_id') == expected.get('workspace_id')
            and path_key(row.get('path')) == path_key(expected.get('path'))
            and row.get('kind') == expected.get('kind')
            and row.get('name') == expected.get('name')
            and bool(row.get('archived')) == bool(expected.get('archived')))


class WorkspaceManager:
    def __init__(self, transport):
        self.transport = transport
        self.lock = asyncio.Lock()

    async def native_catalog(self):
        result = await self.transport.native_workspace_service('GET', 'workspaces')
        return [native_row(item) for item in result.get('workspaces', [])]

    async def metadata(self, path):
        matches = [item for item in await self.native_catalog() if path_key(item['path']) == path_key(path)]
        if len(matches) > 1:
            raise HarnessError('workspace_identity_conflict', 'The folder\'s workspace registration conflicts. Check the registration first.', 409)
        return {'workspace': matches[0] if matches else None}

    async def _status(self, workspace_id):
        return await self.transport.host('GET', '/workspaces/' + workspace_id + '/management')

    async def _host_change(self, workspace_id, phase, **body):
        return await self.transport.host('POST', '/workspaces/' + workspace_id + '/manage', {'phase': phase, **body})

    async def _native_change(self, row, patch, expected):
        return await self.transport.native_workspace_service('PATCH', 'workspaces/' + row['workspace_id'],
            {**patch, 'expected': {key: expected[key] for key in ('name', 'archived', 'path', 'kind')}})

    @staticmethod
    def _desired(reservation):
        before = reservation.get('native_before')
        if before is None:
            return None
        return {**before, **{key: value for key, value in reservation['patch'].items() if key in ('name', 'archived')}}

    async def _recover(self, host_row, native_rows):
        status = await self._status(host_row['id'])
        reservation = status.get('reservation')
        if not reservation:
            return
        before = reservation.get('native_before')
        desired = self._desired(reservation)
        current = next((row for row in native_rows if before and row['workspace_id'] == before['workspace_id']), None)
        transaction_id = reservation['transaction_id']
        if before is None or metadata_equal(current, desired):
            await self._host_change(host_row['id'], 'commit', transaction_id=transaction_id)
        elif metadata_equal(current, before):
            await self._host_change(host_row['id'], 'abort', transaction_id=transaction_id)
        # A user changed metadata in another interface. Keep the durable
        # reservation and report it; never overwrite that newer choice.

    async def _catalog(self, recover=True):
        native_rows = await self.native_catalog()
        harness_rows = (await self.transport.host('GET', '/workspaces')).get('workspaces', [])
        if recover:
            for row in harness_rows:
                if row.get('management_blocked'):
                    try:
                        await self._recover(row, native_rows)
                    except HarnessError:
                        pass
            harness_rows = (await self.transport.host('GET', '/workspaces')).get('workspaces', [])
            native_rows = await self.native_catalog()
        by_path = {path_key(row['path']): row for row in native_rows}
        if len(by_path) != len(native_rows):
            raise HarnessError('workspace_identity_conflict', 'Workspace registration paths conflict. No management operation was performed.', 409)
        linked_native = set()
        unified = []
        for row in harness_rows:
            native = by_path.get(path_key(row.get('path')))
            if native:
                linked_native.add(native['workspace_id'])
            unified.append({**row, 'harness_workspace_id': row['id'],
                'native_workspace_id': native['workspace_id'] if native else None,
                'name': native['name'] if native else row.get('name', row.get('title', '')),
                'title': native['name'] if native else row.get('title', row.get('name', '')),
                'archived': native['archived'] if native else bool(row.get('archived')),
                'kind': native['kind'] if native else 'workspace',
                'status': native['status'] if native else 'ready'})
        for native in native_rows:
            if native['workspace_id'] in linked_native:
                continue
            unified.append({**native, 'id': native['workspace_id'], 'harness_workspace_id': None,
                'native_workspace_id': native['workspace_id'], 'title': native['name'], 'session_ids': [],
                'management_blocked': False})
        return {'workspaces': unified}

    async def catalog(self):
        async with self.lock:
            return await self._catalog()

    async def harness_catalog(self):
        catalog = await self.catalog()
        return {'workspaces': [row for row in catalog['workspaces'] if row['harness_workspace_id']]}

    async def _recover_failed_apply(self, host_id, transaction_id, original):
        """Confirm an uncertain commit before rollback, retaining locks on doubt."""
        try:
            status = await self._status(host_id)
            if status['workspace'].get('last_transaction_id') == transaction_id:
                return True
            reservation = status.get('reservation')
            if not reservation or reservation['transaction_id'] != transaction_id:
                raise HarnessError('workspace_recovery_required', 'The workspace management result is unconfirmed. Refresh and retry.', 409)
            before = reservation.get('native_before')
            desired = self._desired(reservation)
            current = next((row for row in await self.native_catalog() if before and row['workspace_id'] == before['workspace_id']), None)
            if before is not None and not (metadata_equal(current, before) or metadata_equal(current, desired)):
                raise HarnessError('workspace_recovery_required', 'The workspace name or status changed elsewhere. Recover management state first.', 409)
            if before is None or metadata_equal(current, desired):
                try:
                    await self._host_change(host_id, 'commit', transaction_id=transaction_id)
                    return True
                except HarnessError:
                    second = await self._status(host_id)
                    if second['workspace'].get('last_transaction_id') == transaction_id:
                        return True
                    if not second.get('reservation') or second['reservation']['transaction_id'] != transaction_id:
                        raise HarnessError('workspace_recovery_required', 'The workspace management result is unconfirmed. Sources and sessions are retained.', 409)
                    # An unchanged reservation does not prove a timed-out disk
                    # commit is no longer in flight. Leave both sides intact
                    # and recover with the same transaction ID on refresh.
                    raise HarnessError('workspace_recovery_required', 'The workspace save result is unconfirmed. Recovery state is retained.', 409)
            await self._host_change(host_id, 'abort', transaction_id=transaction_id)
            return False
        except HarnessError:
            raise HarnessError('workspace_recovery_required', 'Workspace management is incomplete. Recovery state, files, and sessions are retained. Refresh and retry.', 409) from None

    async def manage(self, identity, patch):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', identity or ''):
            raise HarnessError('workspace_identity_invalid', 'The workspace identifier is invalid.', 422)
        if not isinstance(patch, dict) or not patch or set(patch) - {'name', 'archived'}:
            raise HarnessError('workspace_input_invalid', 'The workspace management request is invalid.', 422)
        patch = deepcopy(patch)
        if 'name' in patch:
            if not isinstance(patch['name'], str) or not patch['name'].strip() or len(patch['name'].strip()) > 100 or re.search(r'[\0\r\n]', patch['name']):
                raise HarnessError('workspace_input_invalid', 'The workspace name must contain 1 to 100 characters.', 422)
            patch['name'] = patch['name'].strip()
        if 'archived' in patch and not isinstance(patch['archived'], bool):
            raise HarnessError('workspace_input_invalid', 'The workspace removal or restoration state is invalid.', 422)
        async with self.lock:
            rows = (await self._catalog())['workspaces']
            row = next((item for item in rows if identity in (item['id'], item['native_workspace_id'], item['harness_workspace_id'])), None)
            if not row:
                raise HarnessError('workspace_missing', 'The workspace is not registered.', 404)
            if row.get('kind') in ('system', 'general'):
                raise HarnessError('workspace_protected', 'The default workspace cannot be renamed or removed.', 403)
            if row.get('management_blocked'):
                raise HarnessError('workspace_recovery_required', 'This workspace has an unfinished management operation. Refresh and retry.', 409)
            native = next((item for item in await self.native_catalog() if item['workspace_id'] == row['native_workspace_id']), None)
            if row['native_workspace_id'] and not metadata_equal(native, {
                    **row, 'workspace_id': row['native_workspace_id']}):
                raise HarnessError('workspace_revision_changed', 'The workspace directory or metadata just changed. Refresh and retry.', 409)
            host_id = row['harness_workspace_id']
            transaction_id = None
            if host_id:
                prepared = await self._host_change(host_id, 'prepare', **patch,
                    **({'native_workspace_id': native['workspace_id'], 'native_before': snapshot(native)} if native else {}))
                transaction_id = prepared['reservation']['transaction_id']
            try:
                if native:
                    await self._native_change(native, patch, native)
                if host_id:
                    await self._host_change(host_id, 'commit', transaction_id=transaction_id)
            except HarnessError as error:
                if not host_id or not await self._recover_failed_apply(host_id, transaction_id, error):
                    raise error
            updated = next(item for item in (await self._catalog(recover=False))['workspaces'] if item['id'] == row['id'])
            operation = 'archive' if patch.get('archived') is True else 'restore' if patch.get('archived') is False else 'rename'
            return {'workspace': updated, 'operation': operation, 'files_deleted': False, 'sessions_deleted': False}

    async def register(self, body):
        async with self.lock:
            rows = (await self._catalog())['workspaces']
        existing = next((row for row in rows if path_key(row['path']) == path_key(body['path'])), None)
        if existing and existing.get('archived'):
            await self.manage(existing['id'], {'archived': False})
        return await self.transport.host('POST', '/workspaces', body)
