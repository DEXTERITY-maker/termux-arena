#!/usr/bin/env python3
"""Nimbus AI — лёгкий веб-чат с моделями DeepSeek. Только стандартная библиотека."""
import json
import os
import sys
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

MODELS = [
    {"id": "deepseek-chat", "name": "DeepSeek Chat (V3)", "desc": "Быстрый универсальный диалог"},
    {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner (R1)", "desc": "Пошаговые рассуждения"},
]


def load_env():
    env = ROOT.parent / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def api_key():
    return os.environ.get("DEEPSEEK_API_KEY", "").strip()


def fetch_models():
    """Пробуем взять список моделей у API, иначе — встроенный."""
    key = api_key()
    if not key:
        return MODELS
    req = urllib.request.Request(
        f"{API_BASE}/models", headers={"Authorization": f"Bearer {key}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
        known = {m["id"]: m for m in MODELS}
        out = []
        for m in data.get("data", []):
            mid = m.get("id")
            if not mid:
                continue
            out.append(known.get(mid, {"id": mid, "name": mid, "desc": "Модель DeepSeek"}))
        return out or MODELS
    except Exception:
        return MODELS


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[nimbus] " + fmt % args + "\n")

    # --- helpers ---
    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, name, ctype):
        p = ROOT / "static" / name
        if not p.exists():
            self.send_json({"error": "not found"}, 404)
            return
        body = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # --- routes ---
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self.send_file("index.html", "text/html; charset=utf-8")
        elif path == "/app.js":
            self.send_file("app.js", "application/javascript; charset=utf-8")
        elif path == "/style.css":
            self.send_file("style.css", "text/css; charset=utf-8")
        elif path == "/api/models":
            self.send_json({"models": fetch_models(), "hasKey": bool(api_key())})
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path.split("?")[0] != "/api/chat":
            self.send_json({"error": "not found"}, 404)
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            self.send_json({"error": "bad request"}, 400)
            return

        key = api_key()
        if not key:
            self.send_json({"error": "DEEPSEEK_API_KEY не задан (см. .env)"}, 400)
            return

        body = json.dumps({
            "model": payload.get("model", "deepseek-chat"),
            "messages": payload.get("messages", []),
            "temperature": payload.get("temperature", 0.7),
            "stream": True,
        }).encode()
        req = urllib.request.Request(
            f"{API_BASE}/chat/completions", data=body,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
        )
        try:
            upstream = urllib.request.urlopen(req, timeout=180)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            self.send_json({"error": f"DeepSeek {e.code}: {detail}"}, 502)
            return
        except Exception as e:
            self.send_json({"error": f"Сеть: {e}"}, 502)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            for raw in upstream:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    self.wfile.write(b"data: [DONE]\n\n")
                    break
                try:
                    d = json.loads(chunk)
                    delta = d["choices"][0].get("delta", {})
                except Exception:
                    continue
                out = {}
                if delta.get("content"):
                    out["content"] = delta["content"]
                if delta.get("reasoning_content"):
                    out["reasoning"] = delta["reasoning_content"]
                if out:
                    self.wfile.write(
                        b"data: " + json.dumps(out, ensure_ascii=False).encode() + b"\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            upstream.close()


def main():
    load_env()
    port = int(os.environ.get("PORT", sys.argv[1] if len(sys.argv) > 1 else 8080))
    host = os.environ.get("HOST", "0.0.0.0")
    if not api_key():
        print("[nimbus] ВНИМАНИЕ: DEEPSEEK_API_KEY не задан. Создай .env с ключом.")
    print(f"[nimbus] Nimbus AI на http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
