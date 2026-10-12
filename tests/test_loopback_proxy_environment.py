"""Loopback proxy regression with disposable HTTP fixtures; no model calls."""
import asyncio
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import storage_paths


@contextmanager
def fixture_server(status):
    """The proxy fixture returns an error without forwarding anywhere."""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            body = b"local fixture" if status == 200 else b"proxy fixture"
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port), requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def no_proxy_tokens(value):
    return [token.strip().casefold() for token in value.split(",") if token.strip()]


class LoopbackProxyEnvironmentTests(unittest.TestCase):
    def setUp(self):
        # Path selection creates no directories and touches no application state.
        self.storage = storage_paths.StoragePaths(ROOT, ROOT)

    def test_registry_proxy_502_is_bypassed_only_for_loopback(self):
        with fixture_server(200) as (local_url, local_requests), \
                fixture_server(502) as (proxy_url, proxy_requests):
            # HTTPX consults this function even with no HTTP_PROXY variable on
            # Windows. Model the registry fallback without editing the registry
            # or reading the machine's configured proxy or credentials.
            def registry_proxies():
                return {
                    "http": proxy_url,
                    "https": proxy_url,
                    "no": os.environ.get("no_proxy", os.environ.get("NO_PROXY", "")),
                }

            async def request_statuses():
                async with httpx.AsyncClient(timeout=3) as client:
                    blocked = await client.get(local_url + "/health")
                self.assertEqual(blocked.status_code, 502)
                self.assertEqual(local_requests, [])

                child_environment = self.storage.child_environment()
                self.assertEqual(dict(os.environ), {})
                os.environ.update(child_environment)
                async with httpx.AsyncClient(timeout=3) as client:
                    local = await client.get(local_url + "/health")
                    external = await client.get("http://provider.example.test/v1/models")
                self.assertEqual(local.status_code, 200)
                self.assertEqual(external.status_code, 502)

            with patch.dict(os.environ, {}, clear=True), \
                    patch("httpx._utils.getproxies", side_effect=registry_proxies):
                asyncio.run(request_statuses())

            self.assertEqual(local_requests, ["/health"])
            self.assertEqual(proxy_requests, [
                local_url + "/health", "http://provider.example.test/v1/models"
            ])

    def test_existing_bypass_entries_and_cloud_proxy_are_preserved(self):
        # A plain mapping can represent both case spellings even on Windows,
        # where the actual process environment treats names case insensitively.
        parent_environment = {
            "NO_PROXY": " .internal.example , localhost ",
            "no_proxy": "build.example,127.0.0.1",
            "HTTP_PROXY": "http://proxy.example.test:8888",
            "HTTPS_PROXY": "http://proxy.example.test:8888",
            "ALL_PROXY": "http://proxy.example.test:8888",
        }
        before = dict(parent_environment)
        with patch.object(os, "environ", parent_environment):
            additions = self.storage.child_environment()
        self.assertEqual(parent_environment, before)
        self.assertEqual(additions["NO_PROXY"], additions["no_proxy"])
        tokens = no_proxy_tokens(additions["NO_PROXY"])
        for hostname in (".internal.example", "build.example", "127.0.0.1", "localhost", "::1"):
            self.assertIn(hostname, tokens)
        child = {**parent_environment, **additions}
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            self.assertEqual(child[name], before[name])

    def test_repeated_launch_is_idempotent_and_deduplicates_loopback(self):
        parent_environment = {
            "NO_PROXY": "localhost,LOCALHOST,127.0.0.1,::1,.internal.example",
            "no_proxy": "127.0.0.1,.internal.example",
        }
        with patch.object(os, "environ", parent_environment):
            first = self.storage.child_environment()
        with patch.object(os, "environ", {**parent_environment, **first}):
            second = self.storage.child_environment()
        self.assertEqual(first["NO_PROXY"], second["NO_PROXY"])
        self.assertEqual(first["no_proxy"], second["no_proxy"])
        tokens = no_proxy_tokens(second["NO_PROXY"])
        self.assertEqual(len(tokens), len(set(tokens)))
        for hostname in ("127.0.0.1", "localhost", "::1"):
            self.assertEqual(tokens.count(hostname), 1)

    def test_existing_wildcard_bypass_remains_present(self):
        with patch.object(os, "environ", {"NO_PROXY": "*"}):
            additions = self.storage.child_environment()
        self.assertIn("*", no_proxy_tokens(additions["NO_PROXY"]))
        self.assertEqual(additions["NO_PROXY"], additions["no_proxy"])


if __name__ == "__main__":
    unittest.main()
