"""Local demo acceptance. Never configures or calls a real model provider."""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from runtime_paths import python_executable
PYTHON = python_executable('portal')
REPORT = ROOT / 'reports' / 'integration-acceptance.json'
BASE = 'http://127.0.0.1:3791'


def request(method, path, **kwargs):
    with httpx.Client(trust_env=False, timeout=90) as client:
        response = client.request(method, BASE + path, **kwargs)
        response.raise_for_status()
        return response.json()


def prepare():
    settings = request('GET', '/api/settings')
    if settings.get('base_url') or settings.get('model') or settings.get('api_key_set'):
        raise RuntimeError('A user provider exists; acceptance refuses to issue any model request.')
    lesson = request('POST', '/api/demo-lesson')
    prior = request('GET', '/api/attempts')['items']
    question = '[Software acceptance fixture, not a student answer] Given that a member cannot code in Python, what is the probability they know photography?'
    attempt = next((a for a in prior if a['lesson_id'] == lesson['id'] and a['question'] == question), None)
    if not attempt:
        attempt = request('POST', '/api/lessons/' + lesson['id'] + '/attempts', json={
            'question': question,
            'answer': '[Software acceptance fixture, not a student answer] Of the 60 members who cannot code in Python, 12 know photography, so the probability is 12/60=0.2.',
        })
    for _ in range(60):
        current = next(a for a in request('GET', '/api/attempts')['items'] if a['id'] == attempt['id'])
        if current['status'] not in ('queued', 'grading'):
            break
        time.sleep(1)
    assert current['status'] == 'saved', current['status']
    assert current['dt_session_id'], 'Native DeepTutor first-answer session was not retained'
    report = {
        'scope': 'Independent local contest demo; no live model generation',
        'lesson_id': lesson['id'], 'classroom_id': lesson['classroom_id'],
        'material_id': lesson['material_id'], 'dt_course_id': lesson['dt_course_id'],
        'attempt_id': current['id'], 'dt_session_id': current['dt_session_id'],
        'source_course_answer_association': True,
        'answer_saved_without_model': True,
        'model_feedback_verified': False,
        'restart_verified': False,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


def restart():
    report = json.loads(REPORT.read_text('utf-8'))
    before = request('GET', '/api/export-records')
    for action in ('stop', 'start'):
        result = subprocess.run([str(PYTHON), '-I', '-B', str(ROOT / 'scripts' / 'portal_runtime.py'), action], cwd=ROOT, check=False)
        if result.returncode:
            raise RuntimeError('Combined launcher failed: ' + action)
    after = request('GET', '/api/export-records')
    for table in ('materials', 'lessons', 'attempts'):
        assert before[table] == after[table], 'Records changed after restart: ' + table
    with httpx.Client(trust_env=False, timeout=30) as client:
        native = client.get('http://127.0.0.1:3793/api/classroom', params={'id': report['classroom_id']})
        native.raise_for_status()
        payload = native.json()
        classroom = payload.get('data', payload)['classroom']
        assert len(classroom['scenes']) == 3
        home = client.get('http://127.0.0.1:3793/')
        assert 'http://127.0.0.1:3791' in home.headers.get('content-security-policy', '')
        assert not home.headers.get('x-frame-options')
        video = client.get(BASE + '/api/demo-video', headers={'Range': 'bytes=0-1023'})
        assert video.status_code == 206 and b'ftyp' in video.content[:32]
    result = subprocess.run([str(PYTHON), '-I', '-B', str(ROOT / 'scripts' / 'portal_runtime.py'), 'status'], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', check=True)
    status = json.loads(result.stdout)
    assert {v['port'] for v in status['listeners']} == {3791,3792,3793,3794,3795,8011}
    assert all(v['host'] in ('127.0.0.1', '::1') for v in status['listeners'])
    report.update(restart_verified=True, classroom_preserved=True, video_http_range_verified=True,
                  iframe_origin_verified=True, all_services_loopback=True, runtime=status)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'restart'])
    mode = parser.parse_args().action
    prepare() if mode == 'prepare' else restart()
