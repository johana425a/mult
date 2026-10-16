"""Verify actual tokenization while all network reads are explicitly blocked."""
from __future__ import annotations
import json
import os
from pathlib import Path
import socket
import sys
import time
from unittest.mock import patch

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from offline_tokenizer import configure_tokenizer_cache


def main():
    start = time.monotonic()
    os.environ['TIKTOKEN_CACHE_DIR'] = 'unused-other-application-cache'
    cache = configure_tokenizer_cache(ROOT)
    attempts = []

    def blocked(*args, **kwargs):
        attempts.append('network-call')
        raise AssertionError('Offline tokenization attempted a network read')

    with patch('socket.create_connection', blocked), patch.object(socket.socket, 'connect', blocked), \
            patch('urllib.request.urlopen', blocked), patch('requests.sessions.Session.request', blocked), \
            patch('tiktoken.load.read_file', blocked):
        import tiktoken
        from deeptutor.services.session import context_builder
        count_tokens = context_builder.count_tokens
        from deeptutor.agents.loop.context_budget import detect_counter_name
        from deeptutor.agents.research.utils.token_tracker import count_tokens_with_tiktoken
        text = '图文课堂：条件概率等于 12/60 = 0.2。 Offline tokenizer verification.'
        counts = {name: len(tiktoken.get_encoding(name).encode(text)) for name in tiktoken.list_encoding_names()}
        native = count_tokens(text)
        assert native == counts['cl100k_base'] and native > 0
        assert detect_counter_name() == 'cl100k_base'
        assert count_tokens_with_tiktoken(text, 'qwen3.5-4b-local') == counts['cl100k_base']
        assert count_tokens_with_tiktoken(text, 'gpt-4o') == counts['o200k_base']
        assert not attempts, attempts
    result = {'root': str(ROOT), 'cache': str(cache), 'actual_native_count_tokens': native,
              'python_executable': sys.executable, 'tiktoken_module': tiktoken.__file__,
              'native_counter_module': context_builder.__file__,
              'all_upstream_encoding_counts': counts, 'network_attempts': len(attempts),
              'inherited_foreign_cache_overridden': True, 'bytecode_disabled': sys.dont_write_bytecode,
              'models_called': False, 'elapsed_seconds': round(time.monotonic() - start, 3)}
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
