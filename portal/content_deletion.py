"""Permanent classroom deletion, limited to recorded owners. Sources are never unlinked."""
from __future__ import annotations

import asyncio
import re


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        raise ValueError('Invalid content identifier')
    return value


async def _native_delete(bridge, path):
    import httpx
    try:
        await bridge._request('DELETE', path)
    except httpx.HTTPStatusError as error:
        if error.response.status_code != 404:
            raise


async def delete_lesson_content(store, lesson_id, tasks, om, dt, *, timeout=20):
    """Keep a deleting row for interrupted cleanup; no backup/recycle-bin copy is created.

    Cooperative portal tasks finish their upstream handshake before stopping,
    so even a delayed submission retains the ID needed to stop and purge it.
    """
    _id(lesson_id)
    original = store.begin_lesson_delete(lesson_id)
    if original is None:
        return
    owned_attempts = [a for a in store.list('attempts') if a['lesson_id'] == lesson_id]
    pending = [task for key, task in list(tasks.items())
               if (key == lesson_id or key in {a['id'] for a in owned_attempts}) and not task.done()]
    deadline = asyncio.get_running_loop().time() + timeout
    while pending:
        for attempt in store.list('attempts'):
            if attempt['lesson_id'] == lesson_id and attempt.get('dt_session_id'):
                task = tasks.get(attempt['id'])
                if task and not task.done():
                    task.cancel()
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise RuntimeError('The task is stopping and deletion is unfinished. Try deleting again shortly.')
        _, pending = await asyncio.wait(pending, timeout=min(remaining, 0.2))
    # Handshake completion may have supplied additional upstream IDs.
    item = store.get('lessons', lesson_id)
    if item is None:
        return
    others = [x for x in store.list('lessons') if x['id'] != lesson_id]
    if item.get('job_id') and not any(x.get('job_id') == item['job_id'] for x in others):
        protected = sorted({_id(x['classroom_id']) for x in others if x.get('classroom_id')})
        await om.delete_job(_id(item['job_id']), preserve_classroom_ids=protected)
    if item.get('classroom_id') and not any(x.get('classroom_id') == item['classroom_id'] for x in others):
        await om.delete_classroom(_id(item['classroom_id']))
    all_attempts = store.list('attempts')
    for attempt in [a for a in all_attempts if a['lesson_id'] == lesson_id]:
        session = attempt.get('dt_session_id')
        if session and not any(a['lesson_id'] != lesson_id and a.get('dt_session_id') == session for a in all_attempts):
            await _native_delete(dt, '/api/sessions/' + _id(session))
    # Course deletion detaches conversations; it never deletes materials.
    course = item.get('dt_course_id')
    if course and not any(x.get('dt_course_id') == course for x in others):
        await _native_delete(dt, '/api/courses/' + _id(course))
    # Reading collections may have independent user conversations. Their materials
    # and collection stay intact; removing the generated course only drops its link.
    store.finish_lesson_delete(lesson_id)
