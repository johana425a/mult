"""Use verified, application-owned tiktoken tables without a first-use download."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

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


def configure_tokenizer_cache(root: Path | None = None) -> Path:
    """Fail explicitly on missing/corrupt tables rather than fetching a repair."""
    cache = (root or ROOT) / 'runtime' / 'tiktoken-cache'
    for name, url, expected in TABLES:
        path = cache / cache_key(url)
        if not path.is_file():
            raise RuntimeError('Bundled offline tokenizer table is missing: ' + name)
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise RuntimeError('Bundled offline tokenizer table failed SHA256: ' + name)
    # -I ignores Python-specific environment options, not this library option.
    # Never reuse another application's inherited token cache or temporary root.
    os.environ['TIKTOKEN_CACHE_DIR'] = str(cache.resolve())
    return cache
