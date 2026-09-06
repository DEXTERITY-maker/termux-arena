#!/usr/bin/env python3
"""Тесты сервера Nimbus AI против локального mock-сервера DeepSeek."""
import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MOCK_STATE = {"mode": "ok", "last": None}


class MockDeepSeek(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer test-key":
            self._json({"error": {"message": "bad key"}}, 401)
            return
        if self.path == "/models":
            if MOCK_STATE["mode"] == "models_fail":
                self._json({"error": {"message": "boom"}}, 500)
                return
            self._json({"data": [{"id": "deepseek-reasoner"}, {"id": "deepseek-chat"},
                                 {"id": "deepseek-coder"}]})
        else:
            self._json({"error": {"message": "nf"}}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        MOCK_STATE["last"] = json.loads(self.rfile.read(n))
        mode = MOCK_STATE["mode"]
        if mode == "http_error":
            self._json({"error": {"message": "Insufficient Balance"}}, 402)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()

        def frame(delta, finish=None):
            return ("data: " + json.dumps(
                {"choices": [{"delta": delta, "finish_reason": finish}]}) + "\n\n").encode()

        if mode == "reasoning":
            self.wfile.write(frame({"reasoning_content": "думаю…"}))
            self.wfile.write(frame({"content": "ответ"}))
        elif mode == "truncated":
            self.wfile.write(frame({"content": "часть"}, "length"))
        elif mode == "no_done":
            self.wfile.write(frame({"content": "без DONE"}))
            self.wfile.flush()
            self.close_connection = True
            return
        elif mode == "garbage":
            self.wfile.write(b": keep-alive\n\n")
            self.wfile.write(b"data: {not json}\n\n")
            self.wfile.write(frame({"content": "ок"}))
        else:
            self.wfile.write(frame({"content": "При"}))
            self.wfile.write(frame({"content": "вет"}))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock_port = free_port()
        cls.mock = ThreadingHTTPServer(("127.0.0.1", cls.mock_port), MockDeepSeek)
        cls.mock.daemon_threads = True
        threading.Thread(target=cls.mock.serve_forever, daemon=True).start()

        os.environ["DEEPSEEK_API_KEY"] = "test-key"
        os.environ["DEEPSEEK_BASE_URL"] = f"http://127.0.0.1:{cls.mock_port}"
        import server
        cls.server_mod = server
        cls.port = free_port()
        cls.srv = server.Server(("127.0.0.1", cls.port), server.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        time.sleep(0.2)
        cls.url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()
        cls.mock.shutdown(); cls.mock.server_close()

    def setUp(self):
        MOCK_STATE["mode"] = "ok"
        self.server_mod._models_cache.update(at=0, data=None)

    def get(self, path):
        with urllib.request.urlopen(self.url + path, timeout=10) as r:
            return r.status, json.load(r)

    def chat(self, payload):
        req = urllib.request.Request(
            self.url + "/api/chat", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()


class TestStatic(Base):
    def test_index_served(self):
        with urllib.request.urlopen(self.url + "/", timeout=5) as r:
            body = r.read().decode()
        self.assertIn("Nimbus AI", body)
        self.assertIn("/util.js", body)

    def test_assets(self):
        for path, needle in (("/app.js", "NimbusUtil"), ("/util.js", "createSSEParser"),
                             ("/style.css", "--accent")):
            with urllib.request.urlopen(self.url + path, timeout=5) as r:
                self.assertIn(needle, r.read().decode(), path)

    def test_health(self):
        code, d = self.get("/api/health")
        self.assertEqual(code, 200)
        self.assertTrue(d["ok"] and d["hasKey"])

    def test_404_json(self):
        try:
            self.get("/nope")
            self.fail("ожидался 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

    def test_path_traversal_blocked(self):
        try:
            urllib.request.urlopen(self.url + "/../server.py", timeout=5)
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)


class TestModels(Base):
    def test_live_list_sorted(self):
        code, d = self.get("/api/models")
        self.assertEqual(code, 200)
        ids = [m["id"] for m in d["models"]]
        self.assertEqual(ids, sorted(ids))
        self.assertIn("deepseek-coder", ids)
        self.assertTrue(d["live"])
        self.assertEqual(d["version"], self.server_mod.VERSION)

    def test_known_names_preserved(self):
        _, d = self.get("/api/models")
        chat = [m for m in d["models"] if m["id"] == "deepseek-chat"][0]
        self.assertIn("V3", chat["name"])

    def test_fallback_on_upstream_error(self):
        MOCK_STATE["mode"] = "models_fail"
        _, d = self.get("/api/models")
        self.assertFalse(d["live"])
        self.assertEqual([m["id"] for m in d["models"]],
                         [m["id"] for m in self.server_mod.FALLBACK_MODELS])

    def test_cache_used(self):
        self.get("/api/models")
        MOCK_STATE["mode"] = "models_fail"
        _, d = self.get("/api/models")          # берётся из кэша, не падает в фолбэк
        self.assertTrue(d["live"])


class TestChat(Base):
    def body(self, txt="привет", **kw):
        p = {"model": "deepseek-chat", "messages": [{"role": "user", "content": txt}]}
        p.update(kw)
        return p

    def test_stream_ok(self):
        code, txt = self.chat(self.body())
        self.assertEqual(code, 200)
        self.assertIn('"content": "При"', txt)
        self.assertTrue(txt.rstrip().endswith("[DONE]"))

    def test_reasoning_forwarded(self):
        MOCK_STATE["mode"] = "reasoning"
        _, txt = self.chat(self.body())
        self.assertIn("reasoning", txt)

    def test_truncation_warning(self):
        MOCK_STATE["mode"] = "truncated"
        _, txt = self.chat(self.body())
        self.assertIn("warning", txt)

    def test_garbage_frames_skipped(self):
        MOCK_STATE["mode"] = "garbage"
        code, txt = self.chat(self.body())
        self.assertEqual(code, 200)
        self.assertIn("ок", txt)

    def test_done_always_sent(self):
        MOCK_STATE["mode"] = "no_done"
        _, txt = self.chat(self.body())
        self.assertTrue(txt.rstrip().endswith("[DONE]"))

    def test_upstream_http_error_passthrough(self):
        MOCK_STATE["mode"] = "http_error"
        code, txt = self.chat(self.body())
        self.assertEqual(code, 402)
        self.assertIn("Insufficient Balance", txt)

    def test_temperature_clamped(self):
        self.chat(self.body(temperature=99))
        self.assertEqual(MOCK_STATE["last"]["temperature"], 2.0)
        self.chat(self.body(temperature=-5))
        self.assertEqual(MOCK_STATE["last"]["temperature"], 0.0)

    def test_reasoner_has_no_temperature(self):
        self.chat({"model": "deepseek-reasoner",
                   "messages": [{"role": "user", "content": "x"}], "temperature": 1.4})
        self.assertNotIn("temperature", MOCK_STATE["last"])

    def test_stream_flag_forced(self):
        self.chat(self.body(stream=False))
        self.assertTrue(MOCK_STATE["last"]["stream"])

    def test_empty_messages_rejected(self):
        code, txt = self.chat({"model": "deepseek-chat", "messages": []})
        self.assertEqual(code, 400)
        self.assertIn("Пустая история", txt)

    def test_bad_role_rejected(self):
        code, _ = self.chat({"model": "deepseek-chat",
                             "messages": [{"role": "root", "content": "x"}]})
        self.assertEqual(code, 400)

    def test_unknown_model_rejected(self):
        code, txt = self.chat({"model": "gpt-9",
                               "messages": [{"role": "user", "content": "x"}]})
        self.assertEqual(code, 400)
        self.assertIn("Неизвестная модель", txt)

    def test_blank_messages_rejected(self):
        code, _ = self.chat({"model": "deepseek-chat",
                             "messages": [{"role": "user", "content": "   "}]})
        self.assertEqual(code, 400)

    def test_bad_json(self):
        req = urllib.request.Request(self.url + "/api/chat", data=b"{oops",
                                     headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(e.exception.code, 400)

    def test_wrong_post_route(self):
        req = urllib.request.Request(self.url + "/api/x", data=b"{}")
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(e.exception.code, 404)


class TestUnits(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import server
        self.s = server

    def test_build_payload_strips_empty(self):
        body, err = self.s.build_upstream_payload({
            "model": "deepseek-chat",
            "messages": [{"role": "system", "content": "s"},
                         {"role": "user", "content": ""},
                         {"role": "user", "content": "hi"}]})
        self.assertIsNone(err)
        self.assertEqual(len(body["messages"]), 2)

    def test_trailing_assistant_rejected(self):
        _, err = self.s.build_upstream_payload({
            "messages": [{"role": "user", "content": "a"},
                         {"role": "assistant", "content": "b"}]})
        self.assertIn("ассистента", err)

    def test_only_system_rejected(self):
        _, err = self.s.build_upstream_payload({
            "messages": [{"role": "system", "content": "s"}]})
        self.assertIsNotNone(err)

    def test_non_dict_payload(self):
        _, err = self.s.build_upstream_payload(["x"])
        self.assertIsNotNone(err)

    def test_bad_temperature_falls_back(self):
        body, _ = self.s.build_upstream_payload({
            "temperature": "жарко",
            "messages": [{"role": "user", "content": "a"}]})
        self.assertEqual(body["temperature"], 0.7)

    def test_max_tokens_bounds(self):
        b1, _ = self.s.build_upstream_payload({"max_tokens": 999999,
                                               "messages": [{"role": "user", "content": "a"}]})
        self.assertNotIn("max_tokens", b1)
        b2, _ = self.s.build_upstream_payload({"max_tokens": 100,
                                               "messages": [{"role": "user", "content": "a"}]})
        self.assertEqual(b2["max_tokens"], 100)

    def test_resolve_port(self):
        os.environ.pop("PORT", None)
        self.assertEqual(self.s.resolve_port(["p"]), 8080)
        self.assertEqual(self.s.resolve_port(["p", "9000"]), 9000)
        self.assertEqual(self.s.resolve_port(["p", "мусор"]), 8080)
        self.assertEqual(self.s.resolve_port(["p", "70000"]), 8080)
        os.environ["PORT"] = "7777"
        self.assertEqual(self.s.resolve_port(["p"]), 7777)
        self.assertEqual(self.s.resolve_port(["p", "8123"]), 8123)   # argv важнее
        os.environ.pop("PORT")

    def test_load_env_quotes_and_export(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text('# c\nexport NIMBUS_T1="abc"\nNIMBUS_T2=\'d=e\'\nbroken\n')
            os.environ.pop("NIMBUS_T1", None); os.environ.pop("NIMBUS_T2", None)
            self.s.load_env(p)
            self.assertEqual(os.environ["NIMBUS_T1"], "abc")
            self.assertEqual(os.environ["NIMBUS_T2"], "d=e")

    def test_env_does_not_override(self):
        import tempfile
        os.environ["NIMBUS_T3"] = "keep"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("NIMBUS_T3=other\n")
            self.s.load_env(p)
        self.assertEqual(os.environ["NIMBUS_T3"], "keep")

    def test_mask(self):
        self.assertNotIn("secret", self.s.mask("sk-secretsecretsecret"))
        self.assertEqual(self.s.mask("short"), "…")

    def test_base_url_trailing_slash(self):
        os.environ["DEEPSEEK_BASE_URL"] = "https://x.example/v1/"
        self.assertEqual(self.s.base_url(), "https://x.example/v1")


class TestNoKey(unittest.TestCase):
    """Сервер без ключа должен отвечать 503, а не падать."""
    def test_chat_without_key(self):
        import importlib
        os.environ.pop("DEEPSEEK_API_KEY", None)
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import server
        importlib.reload(server)
        port = free_port()
        srv = server.Server(("127.0.0.1", port), server.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        time.sleep(0.15)
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/chat",
                data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode(),
                headers={"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(e.exception.code, 503)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/models", timeout=5) as r:
                self.assertFalse(json.load(r)["hasKey"])
        finally:
            srv.shutdown(); srv.server_close()
            os.environ["DEEPSEEK_API_KEY"] = "test-key"


if __name__ == "__main__":
    unittest.main(verbosity=2)
