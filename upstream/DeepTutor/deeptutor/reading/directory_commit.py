"""Recoverable directory publication for an existing reading material.

The caller holds the material lock. Windows readers/indexers can briefly deny
directory renames; never delete the old copy when a rollback is also denied.
"""
import json
import logging
from pathlib import Path
import shutil
import uuid

from deeptutor.reading.models import ReadingError
from deeptutor.services.file_io import _atomic_replace, atomic_write_json

log=logging.getLogger(__name__)


class ReadingStorageBusy(ReadingError):
    code='reading_storage_busy'
    stage='publish_material'
    retryable=True

    def __init__(self, diagnostic_id):
        self.diagnostic_id=diagnostic_id
        super().__init__('Reading files are temporarily in use. Your saved material has been retained; retry shortly. '
                         'Diagnostic: '+diagnostic_id)


def journal_path(material):
    return material.parent / ('.'+material.name+'.replace.json')


def checked_paths(material, stage, backup):
    root=material.parent.resolve()
    for path in (material,stage,backup):
        if path.parent.resolve()!=root or path.is_symlink() or path.is_junction():
            raise ValueError('Material publication requires sibling plain directories')
        path.resolve().relative_to(root)
    if len({material,stage,backup})!=3 or not stage.name.endswith('.staging') or not backup.name.endswith('.backup'):
        raise ValueError('Invalid material publication paths')


def cleanup(material,stage,backup):
    # Only called with a readable committed or restored material in place.
    if not (material/'manifest.json').is_file():return
    for path in (stage,backup):
        try:shutil.rmtree(path)
        except FileNotFoundError:pass
        except PermissionError:pass  # Keep the journal and retry cleanup on reopening.
    if not stage.exists() and not backup.exists():
        try:journal_path(material).unlink(missing_ok=True)
        except PermissionError:pass


def recover(material):
    journal=journal_path(material)
    if not journal.exists():return
    record=json.loads(journal.read_text('utf-8'))
    if record.get('schema')!=1 or record.get('material')!=material.name:
        raise ReadingError('Invalid reading recovery record; saved copies have been retained.')
    names=[record.get('stage'),record.get('backup')]
    if any(not isinstance(n,str) or Path(n).name!=n or '/' in n or '\\' in n or ':' in n for n in names):
        raise ReadingError('Invalid reading recovery path; saved copies have been retained.')
    stage,backup=[material.parent/n for n in names]
    checked_paths(material,stage,backup)
    try:
        if not material.exists():
            if backup.exists():_atomic_replace(backup,material)
            elif not record.get('had_original') and stage.exists():_atomic_replace(stage,material)
            else:raise ReadingError('Reading recovery needs attention; saved copies have been retained.')
        elif backup.exists() and stage.exists():
            raise ReadingError('Ambiguous reading recovery; saved copies have been retained.')
    except PermissionError as exc:
        raise ReadingStorageBusy(record['diagnostic_id']) from exc
    cleanup(material,stage,backup)


def publish(material,stage,backup):
    checked_paths(material,stage,backup)
    recover(material)
    diagnostic=uuid.uuid4().hex[:12]
    record={'schema':1,'material':material.name,'stage':stage.name,'backup':backup.name,
            'had_original':material.exists(),'diagnostic_id':diagnostic}
    atomic_write_json(journal_path(material),record)
    try:
        if material.exists():_atomic_replace(material,backup)
        try:_atomic_replace(stage,material)
        except BaseException:
            if backup.exists() and not material.exists():_atomic_replace(backup,material)
            raise
    except PermissionError as exc:
        # The original may be in backup if both publication and rollback fail.
        # Leave both copies and the recovery record for the next read/restart.
        log.warning('Reading publication blocked; diagnostic=%s',diagnostic,exc_info=True)
        if material.exists() and not backup.exists():cleanup(material,stage,backup)
        raise ReadingStorageBusy(diagnostic) from exc
    except BaseException:
        if material.exists() and not backup.exists():cleanup(material,stage,backup)
        raise
    else:
        cleanup(material,stage,backup)
