"""Preserve real Windows urllib proxy discovery while exempting local services.

Registry mappings are mocked. HTTP fixtures bind only loopback and never
forward requests; the non-exempt host is also loopback, so no external network
or real registry settings/credentials are accessed.
"""
import asyncio
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
from urllib import request as urlrequest

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import storage_paths


@contextmanager
def fixture_server(status):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            body = b"local fixture" if status == 200 else b"proxy fixture"
            self.send_response(status)
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


@unittest.skipUnless(hasattr(urlrequest, "getproxies_registry"), "Windows registry discovery")
class WindowsRegistryProxyPreservationTests(unittest.TestCase):
    def setUp(self):
        self.storage = storage_paths.StoragePaths(ROOT, ROOT)

    def test_real_getproxies_preserves_registry_routes_after_no_proxy_is_added(self):
        routes = {"http": "http://proxy.example.test:8888",
                  "https": "http://proxy.example.test:8888",
                  "all": "http://proxy.example.test:8888"}
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(urlrequest, "getproxies_registry", return_value=routes) as registry:
            self.assertEqual(urlrequest.getproxies(), routes)
            additions = self.storage.child_environment()
            self.assertEqual(dict(os.environ), {})
            self.assertGreaterEqual(registry.call_count, 2)
            for scheme, route in routes.items():
                self.assertEqual(additions[scheme.upper() + "_PROXY"], route)
            os.environ.update(additions)
            actual = urlrequest.getproxies()
            for scheme, route in routes.items():
                self.assertEqual(actual[scheme], route)
            self.assertEqual(actual["no"], "127.0.0.1,localhost,::1")

    def test_httpx_local_bypass_keeps_nonexempt_host_on_registry_proxy(self):
        with fixture_server(200) as (local_url, local_requests), \
                fixture_server(502) as (proxy_url, proxy_requests):
            # This address intentionally falls outside the three configured
            # exemptions. It remains loopback even if a regression uses a
            # direct connection, and the proxy never forwards it.
            other_url = local_url.replace("127.0.0.1", "127.0.0.2") + "/v1/models"
            routes = {"http": proxy_url, "https": proxy_url}

            async def request_statuses():
                async with httpx.AsyncClient(timeout=3) as client:
                    before = await client.get(local_url + "/health")
                    other_before = await client.get(other_url)
                self.assertEqual(before.status_code, 502)
                self.assertEqual(other_before.status_code, 502)
                self.assertEqual(local_requests, [])
                additions = self.storage.child_environment()
                self.assertEqual(dict(os.environ), {})
                os.environ.update(additions)
                async with httpx.AsyncClient(timeout=3) as client:
                    local = await client.get(local_url + "/health")
                    other_after = await client.get(other_url)
                self.assertEqual(local.status_code, 200)
                self.assertEqual(other_after.status_code, 502)

            with patch.dict(os.environ, {}, clear=True), \
                    patch.object(urlrequest, "getproxies_registry", return_value=routes):
                asyncio.run(request_statuses())
            self.assertEqual(local_requests, ["/health"])
            self.assertEqual(proxy_requests, [local_url + "/health", other_url, other_url])

    def test_explicit_environment_routes_are_not_replaced_from_registry(self):
        inherited = {"HTTP_PROXY": "http://explicit-http.example.test:8888",
                     "HTTPS_PROXY": "http://explicit-https.example.test:8888",
                     "ALL_PROXY": "http://explicit-all.example.test:8888",
                     "NO_PROXY": ".internal.example"}
        with patch.dict(os.environ, inherited, clear=True), \
                patch.object(urlrequest, "getproxies_registry") as registry:
            before = dict(os.environ)
            additions = self.storage.child_environment()
            self.assertEqual(dict(os.environ), before)
            registry.assert_not_called()
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
                self.assertNotIn(name, additions)
                self.assertEqual({**before, **additions}[name], inherited[name])
            self.assertIn(".internal.example", additions["NO_PROXY"].split(","))

    def test_partial_environment_proxy_does_not_enable_missing_registry_routes(self):
        # urllib's existing semantics already avoid registry fallback when any
        # environment proxy route exists; preserve that choice exactly.
        inherited = {"HTTP_PROXY": "http://explicit-http.example.test:8888"}
        with patch.dict(os.environ, inherited, clear=True), \
                patch.object(urlrequest, "getproxies_registry") as registry:
            baseline = urlrequest.getproxies()
            additions = self.storage.child_environment()
            os.environ.update(additions)
            actual = urlrequest.getproxies()
            self.assertEqual(actual["http"], baseline["http"])
            self.assertNotIn("https", actual)
            self.assertNotIn("all", actual)
            registry.assert_not_called()

    def test_preexisting_no_proxy_only_keeps_previous_effective_direct_routes(self):
        with patch.dict(os.environ, {"NO_PROXY": ".internal.example"}, clear=True), \
                patch.object(urlrequest, "getproxies_registry") as registry:
            additions = self.storage.child_environment()
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
                self.assertNotIn(name, additions)
            registry.assert_not_called()

    def test_empty_proxy_variable_does_not_lose_effective_registry_route(self):
        route = "http://registry-proxy.example.test:8888"
        with patch.dict(os.environ, {"HTTP_PROXY": ""}, clear=True), \
                patch.object(urlrequest, "getproxies_registry", return_value={"http": route}):
            self.assertEqual(urlrequest.getproxies(), {"http": route})
            additions = self.storage.child_environment()
            self.assertEqual(os.environ["HTTP_PROXY"], "")
            self.assertEqual(additions["HTTP_PROXY"], route)
            os.environ.update(additions)
            self.assertEqual(urlrequest.getproxies()["http"], route)


if __name__ == "__main__":
    unittest.main()
