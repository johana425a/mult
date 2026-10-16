"""Reversible model references for native tasks and image reading, without keys."""
from copy import deepcopy

TASK_FIELDS = ('mode', 'selection', 'overrides', 'deepsteam_default_owner')


def snapshot_defaults(catalog, parsing):
    task = catalog.get('services', {}).get('task', {})
    return {'task': {key: {'present': key in task, 'value': deepcopy(task.get(key))} for key in TASK_FIELDS},
            'image_description_model': {'present': 'image_description_model' in parsing,
                                        'value': deepcopy(parsing.get('image_description_model'))}}


def select_defaults(catalog, parsing, profile_id, vision):
    proposed, document = deepcopy(catalog), deepcopy(parsing)
    llm = proposed.get('services', {}).get('llm', {})
    if not str(profile_id).startswith('deepsteam-harness-') or llm.get('active_profile_id') != profile_id:
        raise ValueError('Active managed model changed')
    task = proposed.setdefault('services', {}).setdefault('task', {})
    task['mode'] = 'inherit'
    task['deepsteam_default_owner'] = profile_id
    task.pop('selection', None); task.pop('overrides', None)
    if vision:
        document['image_description_model'] = None
    return proposed, document


def restore_defaults(catalog, parsing, profile_id, original):
    proposed, document = deepcopy(catalog), deepcopy(parsing)
    task = proposed.get('services', {}).get('task', {})
    if (proposed.get('services', {}).get('llm', {}).get('active_profile_id') != profile_id
            or task.get('deepsteam_default_owner') != profile_id):
        return proposed, document, False
    # A new explicit task choice and the image reading choice are independent.
    # Restore each only while it still has the value installed by this owner.
    if task.get('mode') == 'inherit' and not task.get('selection') and not task.get('overrides'):
        for key in TASK_FIELDS:
            item = original.get('task', {}).get(key, {'present': False})
            if item.get('present'):
                task[key] = deepcopy(item.get('value'))
            else:
                task.pop(key, None)
    else:
        task.pop('deepsteam_default_owner', None)
    image = original.get('image_description_model', {'present': False})
    if not document.get('image_description_model'):
        if image.get('present'):
            document['image_description_model'] = deepcopy(image.get('value'))
        else:
            document.pop('image_description_model', None)
    return proposed, document, proposed != catalog or document != parsing
