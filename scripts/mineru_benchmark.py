"""Measure local MinerU speed on this computer with a document you choose.

Runs the installed MinerU worker exactly as the document queue does (the
persistent ``--serve`` worker, physical PDF batches) and reports:

* cold start: the first batch in a fresh worker, including model loading;
* warm batches: later batches in the same worker (models already loaded);
* seconds per page for each number of VLM decoding slots you list;
* how closely the text from each slot setting matches the first setting.

Everything runs on this computer; no document leaves it. Results are real
measurements of local inference, not fixtures. ``--save`` records the fastest
slot setting for this computer in DeepSteam's local state (never in the
installation or source tree).

Example (Windows PowerShell)::

    .\\runtime\\python\\python.exe -I -B scripts\\mineru_benchmark.py --pdf "D:\\Papers\\sample.pdf" --pages 8 --slots 1,2
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integration import document_jobs as jobs  # noqa: E402


def parse_batches(session, source: Path, work: Path, tier: str, pages: int, batch: int) -> list[dict]:
    rows = []
    for start in range(0, pages, batch):
        end = min(start + batch, pages)
        container = work / f'batch-{start + 1}-{end}-{uuid.uuid4().hex[:6]}'
        container.mkdir(parents=True)
        subset, digest = jobs.pdf_subset(source, container, start, end)
        output = container / 'output'
        began = time.monotonic()
        value = session.parse({'schema_version': 1, 'action': 'parse', 'source_path': str(subset),
                               'output_dir': str(output), 'source_sha256': digest,
                               'engine_options': {'tier': tier}, 'request_id': uuid.uuid4().hex},
                              jobs.MINERU_TIMEOUT_SECONDS[tier], cancelled=lambda: False)
        elapsed = time.monotonic() - began
        if not value.get('ok'):
            raise RuntimeError(f'pages {start + 1}-{end}: {value.get("error")}')
        result = json.loads((output / 'result.json').read_text('utf-8'))
        rows.append({'pages': [start + 1, end], 'seconds': round(elapsed, 2),
                     'seconds_per_page': round(elapsed / (end - start), 2),
                     'vlm_used': result.get('inference', {}).get('vlm_used'),
                     'vlm_usage': result.get('inference', {}).get('vlm_usage'),
                     'text': '\n\n'.join(unit.get('text', '') for unit in result.get('units', [])),
                     'inference': result.get('inference', {})})
    return rows


def measure(source: Path, work: Path, tier: str, pages: int, batch: int, slots: int) -> dict:
    python, helper = jobs.mineru_runtime()
    home = work / f'home-{slots}'
    home.mkdir(parents=True)
    started = time.monotonic()
    session = jobs.MinerUSession(python, helper, home, vlm_parallel=slots)
    try:
        rows = parse_batches(session, source, work, tier, pages, batch)
    finally:
        session.close()
    total = time.monotonic() - started
    warm = rows[1:]
    warm_pages = sum(row['pages'][1] - row['pages'][0] + 1 for row in warm)
    vlm = (rows[0]['inference'].get('vlm') or {}) if rows else {}
    return {'requested_slots': slots, 'actual_slots': vlm.get('decoding_slots'), 'tier': tier,
            'first_batch_seconds_including_model_load': rows[0]['seconds'] if rows else None,
            'warm_seconds_per_page': round(sum(row['seconds'] for row in warm) / warm_pages, 2) if warm_pages else None,
            'total_seconds': round(total, 2), 'pages': pages, 'batches': [{k: v for k, v in row.items() if k not in {'text', 'inference'}} for row in rows],
            'model': vlm.get('model'), 'backend': vlm.get('backend'), 'vlm_used': rows[0]['inference'].get('vlm_used') if rows else None,
            '_text': '\n\n'.join(row['text'] for row in rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--pdf', required=True, help='a PDF you choose; it is read, never modified')
    parser.add_argument('--pages', type=int, default=8, help='pages from the start to parse (default 8)')
    parser.add_argument('--tier', default='advanced', choices=sorted(jobs.MINERU_TIERS))
    parser.add_argument('--slots', default='1,2', help='decoding slot settings to compare, e.g. 1,2,4')
    parser.add_argument('--save', action='store_true', help='record the fastest slot setting for this computer')
    args = parser.parse_args()
    source = Path(args.pdf).resolve(strict=True)
    if source.suffix.lower() != '.pdf':
        parser.error('--pdf must be a PDF file')
    python, helper = jobs.mineru_runtime()
    if not python.is_file() or not helper.is_file():
        print(json.dumps({'ok': False, 'error': 'The local MinerU runtime is not installed in this DeepSteam folder.'}))
        return 2
    import pymupdf
    with pymupdf.open(source) as pdf:
        pages = max(1, min(args.pages, len(pdf)))
    slot_values = sorted({int(value) for value in args.slots.split(',') if value.strip()})
    if not slot_values or any(not 1 <= value <= 4 for value in slot_values):
        parser.error('--slots values must be 1 to 4')
    state = jobs.DocumentJobs()
    work = state.cache / ('mineru-benchmark-' + uuid.uuid4().hex[:8])
    work.mkdir(parents=True)
    try:
        runs = [measure(source, work, args.tier, pages, jobs.MINERU_BATCH_PAGES[args.tier], slots) for slots in slot_values]
    finally:
        shutil.rmtree(work, ignore_errors=True)  # Only this run's own folder.
    reference = runs[0].pop('_text')
    for run in runs[1:]:
        run['text_similarity_to_first'] = round(difflib.SequenceMatcher(None, reference, run.pop('_text')).ratio(), 4)
    measured = [run for run in runs if run['warm_seconds_per_page'] is not None] or runs
    best = min(measured, key=lambda run: run['warm_seconds_per_page'] or run['total_seconds'])
    report = {'ok': True, 'kind': 'real local inference measurement', 'document_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'cpu_count': os.cpu_count(), 'batch_pages': jobs.MINERU_BATCH_PAGES[args.tier], 'runs': runs,
              'fastest_slots': best['actual_slots'] or best['requested_slots']}
    if args.save:
        target = state.directory / 'mineru-local.json'
        target.write_text(json.dumps({'vlm_parallel': report['fastest_slots'], 'measured_at': time.time(),
                                      'warm_seconds_per_page': best['warm_seconds_per_page'], 'tier': args.tier}), encoding='utf-8')
        report['saved'] = str(target)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
