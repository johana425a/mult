"""Use verified local tables; repair damaged resources without blocking startup."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import logging
import threading
import uuid
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
TIKTOKEN_VERSION = '0.14.0'
OFFICIAL_SOURCE = 'https://raw.githubusercontent.com/openai/tiktoken/0.14.0/tiktoken_ext/openai_public.py'
TABLES = (
    ('cl100k_base', 'https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken',
     '223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7'),
    ('o200k_base', 'https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken',
     '446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d'),
    ('r50k_base', 'https://openaipublic.blob.core.windows.net/encodings/r50k_base.tiktoken',
     '306cd27f03c1a714eca7108e03d66b7dc042abe8c258b44c199a7ed9838dd930'),
    ('p50k_base', 'https://openaipublic.blob.core.windows.net/encodings/p50k_base.tiktoken',
     '94b5ca7dff4d00767bc256fdd1b27e5b17361d7b8a5f968547f9f23eb70d2069'),
    ('gpt2-vocab', 'https://openaipublic.blob.core.windows.net/gpt-2/encodings/main/vocab.bpe',
     '1ce1664773c50f3e0cc8842619a93edc4624525b728b188a9e0be33b7726adc5'),
    ('gpt2-encoder', 'https://openaipublic.blob.core.windows.net/gpt-2/encodings/main/encoder.json',
     '196139668be63f3b5d6574427317ae82f612a97c5d1cdaf36ed2256dbf636783'),
)


def cache_key(url: str) -> str:
    # This is the URL-derived filename used by upstream tiktoken.load.
    return hashlib.sha1(url.encode('utf-8')).hexdigest()


_repair_lock = threading.Lock()
_repairing: set[str] = set()
_log = logging.getLogger(__name__)


def _verified_bytes(path: Path, expected: str) -> bytes | None:
    try:
        data = path.read_bytes()
        return data if hashlib.sha256(data).hexdigest() == expected else None
    except OSError:
        return None


def _download_table(url: str) -> bytes:
    # Public, pinned vocabulary only. No document or account data is sent.
    with urlopen(url, timeout=10) as response:
        return response.read(64 * 1024 * 1024 + 1)


def _repair_table(cache: Path, table, downloader=None) -> bool:
    name, url, expected = table
    target = cache / cache_key(url)
    temporary = cache / (target.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        if _verified_bytes(target, expected) is not None:
            return True
        data = (downloader or _download_table)(url)
        if len(data) > 64 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('Tokenizer download failed integrity check')
        cache.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(data)
        os.replace(temporary, target)
        _log.info('Repaired tokenizer resource: %s', name)
        return True
    except Exception:
        _log.warning('Tokenizer %s is unavailable; token estimates remain approximate until repair succeeds.', name)
        return False
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _schedule_repairs(cache: Path, missing) -> None:
    key = str(cache)
    with _repair_lock:
        if key in _repairing:
            return
        _repairing.add(key)

    def run():
        try:
            for table in missing:
                _repair_table(cache, table)
        finally:
            with _repair_lock:
                _repairing.discard(key)

    threading.Thread(target=run, name='deepsteam-tokenizer-repair', daemon=True).start()


def configure_tokenizer_cache(root: Path | None = None, *, repair: bool = True) -> Path:
    """Start offline, use existing estimate fallbacks, and repair in the background.

    Do not let tiktoken's unbounded first-use HTTP request stall a chat while a
    repair is pending. A missing table raises locally so existing callers can
    report/use their heuristic counter. Successful repairs become usable without
    a restart; verified evidence is never invented for a corrupt resource.
    """
    cache = ((root or ROOT) / 'runtime' / 'tiktoken-cache').resolve()
    os.environ['TIKTOKEN_CACHE_DIR'] = str(cache)
    import tiktoken.load
    original = getattr(tiktoken.load.read_file_cached, '_deepsteam_original', tiktoken.load.read_file_cached)
    known = {url: expected for _, url, expected in TABLES}

    def read_local(blobpath, expected_hash=None):
        if blobpath not in known:
            return original(blobpath, expected_hash)
        expected = known[blobpath]
        if expected_hash is not None and expected_hash != expected:
            raise ValueError('Tokenizer resource version mismatch')
        data = _verified_bytes(cache / cache_key(blobpath), expected)
        if data is None:
            raise RuntimeError('Tokenizer table is being repaired; use an approximate token counter')
        return data

    read_local._deepsteam_original = original
    tiktoken.load.read_file_cached = read_local
    missing = [table for table in TABLES if _verified_bytes(cache / cache_key(table[1]), table[2]) is None]
    if missing:
        _log.warning('%d tokenizer resources require repair; application startup will continue.', len(missing))
        if repair:
            _schedule_repairs(cache, missing)
    return cache
