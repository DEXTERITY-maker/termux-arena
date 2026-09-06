#!/usr/bin/env python3
"""Nimbus AI — лёгкий веб-чат с моделями DeepSeek.

Только стандартная библиотека Python 3.8+. Ключ API никогда не покидает сервер.
"""
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "0.0.1-alpha"
ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"

DEFAULT_BASE_URL = "https://api.deepseek.com"
MAX_BODY = 4 * 1024 * 1024          # 4 МБ — потолок запроса от браузера
UPSTREAM_TIMEOUT = 300              # с
MODELS_TTL = 300                    # с, кэш списка моделей

# Модели, для которых поле temperature не поддерживается API DeepSeek.
NO_TEMPERATURE = ("deepseek-reasoner",)

FALLBACK_MODELS = [
    {"id": "deepseek-chat", "name": "DeepSeek Chat (V3)",
     "desc": "Быстрый универсальный диалог"},
    {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner (R1)",
     "desc": "Пошаговые рассуждения, поле temperature игнорируется"},
]
KNOWN = {m["id"]: m for m in FALLBACK_MODELS}

STATIC_ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/util.js": ("util.js", "application/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}

_models_cache = {"at": 0.0, "data": None}


# --------------------------------------------------------------------------- #
# конфигурация
# --------------------------------------------------------------------------- #
def load_env(*candidates):
    """Читает .env (repo/.env и nimbus/.env). Существующее окружение приоритетнее."""
    paths = [Path(p) for p in candidates] or [ROOT.parent / ".env", ROOT / ".env"]
    for path in paths:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k.startswith("export "):
                k = k[7:].strip()
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            if k:
                os.environ.setdefault(k, v)


def api_key():
    return os.environ.get("DEEPSEEK_API_KEY", "").strip()


def base_url():
    return os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def mask(key):
    return f"{key[:6]}…{key[-4:]}" if len(key) > 12 else "…"


# --------------------------------------------------------------------------- #
# модели
# --------------------------------------------------------------------------- #
def fetch_models(force=False):
    """Список моделей из API DeepSeek с кэшем и фолбэком."""
    import time
    now = time.time()
    if not force and _models_cache["data"] and now - _models_cache["at"] < MODELS_TTL:
        return _models_cache["data"], True

    key = api_key()
    if not key:
        return FALLBACK_MODELS, False

    req = urllib.request.Request(
        f"{base_url()}/models",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
        out = []
        for m in data.get("data", []):
            mid = m.get("id")
            if mid:
                out.append(KNOWN.get(mid, {"id": mid, "name": mid,
                                           "desc": "Модель DeepSeek"}))
        if out:
            out.sort(key=lambda m: m["id"])
            _models_cache.update(at=now, data=out)
            return out, True
    except Exception as e:                                  # noqa: BLE001
        sys.stderr.write(f"[nimbus] список моделей недоступен: {e}\n")
    return FALLBACK_MODELS, False


# --------------------------------------------------------------------------- #
# валидация запроса чата
# --------------------------------------------------------------------------- #
ROLES = ("system", "user", "assistant")


def build_upstream_payload(payload, allowed_ids=None):
    """Проверяет запрос браузера и собирает тело для DeepSeek.

    Возвращает (payload, None) либо (None, "текст ошибки").
    """
    if not isinstance(payload, dict):
        return None, "Ожидался JSON-объект"

    model = payload.get("model") or "deepseek-chat"
    if not isinstance(model, str) or not model.strip():
        return None, "Некорректное поле model"
    model = model.strip()
    if allowed_ids and model not in allowed_ids:
        return None, f"Неизвестная модель: {model}"

    raw = payload.get("messages")
    if not isinstance(raw, list) or not raw:
        return None, "Пустая история сообщений"

    messages = []
    for m in raw:
        if not isinstance(m, dict):
            return None, "Некорректный элемент messages"
        role, content = m.get("role"), m.get("content")
        if role not in ROLES:
            return None, f"Недопустимая роль: {role!r}"
        if not isinstance(content, str):
            return None, "Поле content должно быть строкой"
        if not content.strip():
            continue                      # пустые реплики API отвергает
        messages.append({"role": role, "content": content})

    if not messages or all(m["role"] == "system" for m in messages):
        return None, "Нет ни одного непустого сообщения пользователя"
    if messages[-1]["role"] == "assistant":
        return None, "Последнее сообщение не может быть от ассистента"

    body = {"model": model, "messages": messages, "stream": True}

    if model not in NO_TEMPERATURE:
        try:
            t = float(payload.get("temperature", 0.7))
        except (TypeError, ValueError):
            t = 0.7
        body["temperature"] = min(max(t, 0.0), 2.0)

    mt = payload.get("max_tokens")
    if isinstance(mt, (int, float)) and 1 <= mt <= 8192:
        body["max_tokens"] = int(mt)
    return body, None


def sse(obj):
    return b"data: " + json.dumps(obj, ensure_ascii=False).encode() + b"\n\n"


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"Nimbus/{VERSION}"

    def log_message(self, fmt, *args):
        sys.stderr.write("[nimbus] %s\n" % (fmt % args))

    # ---------- helpers ----------
    def _headers(self, code, ctype, length=None, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self._headers(code, "application/json; charset=utf-8", len(body))
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_static(self, name, ctype):
        path = (STATIC / name).resolve()
        if not str(path).startswith(str(STATIC.resolve())) or not path.is_file():
            self.send_json({"error": "not found"}, 404)
            return
        body = path.read_bytes()
        self._headers(200, ctype, len(body), {"Cache-Control": "no-store"})
        if self.command != "HEAD":
            self.wfile.write(body)

    # ---------- GET ----------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in STATIC_ROUTES:
            self.send_static(*STATIC_ROUTES[path])
        elif path == "/api/models":
            models, live = fetch_models()
            self.send_json({"models": models, "live": live,
                            "hasKey": bool(api_key()), "version": VERSION})
        elif path in ("/api/health", "/healthz"):
            self.send_json({"ok": True, "version": VERSION,
                            "hasKey": bool(api_key()), "baseUrl": base_url()})
        elif path == "/favicon.ico":
            self._headers(204, "image/x-icon", 0)
        else:
            self.send_json({"error": "not found", "path": path}, 404)

    do_HEAD = do_GET

    # ---------- POST ----------
    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/chat":
            self.send_json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.send_json({"error": "Некорректный Content-Length"}, 400)
            return
        if length <= 0:
            self.send_json({"error": "Пустое тело запроса"}, 400)
            return
        if length > MAX_BODY:
            self.send_json({"error": "Слишком большой запрос"}, 413)
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except Exception:                                   # noqa: BLE001
            self.send_json({"error": "Тело запроса не является JSON"}, 400)
            return

        key = api_key()
        if not key:
            self.send_json({"error": "DEEPSEEK_API_KEY не задан — добавьте его в .env "
                                     "и перезапустите сервер"}, 503)
            return

        allowed = {m["id"] for m in fetch_models()[0]}
        body, err = build_upstream_payload(payload, allowed)
        if err:
            self.send_json({"error": err}, 400)
            return

        req = urllib.request.Request(
            f"{base_url()}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode(),
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json",
                     "Accept": "text/event-stream"},
        )
        try:
            upstream = urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:600]
            try:
                detail = json.loads(detail)["error"]["message"]
            except Exception:                               # noqa: BLE001
                pass
            self.send_json({"error": f"DeepSeek {e.code}: {detail}"},
                           502 if e.code >= 500 else e.code)
            return
        except Exception as e:                              # noqa: BLE001
            self.send_json({"error": f"Сеть недоступна: {e}"}, 502)
            return

        self._headers(200, "text/event-stream; charset=utf-8", None,
                      {"Cache-Control": "no-cache, no-transform",
                       "Connection": "close", "X-Accel-Buffering": "no"})
        self.close_connection = True
        self.stream(upstream)

    def stream(self, upstream):
        """Перекладывает SSE-поток DeepSeek в поток браузера."""
        sent_done = False
        try:
            for raw in upstream:
                line = raw.decode("utf-8", "replace").strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    self.wfile.write(b"data: [DONE]\n\n")
                    sent_done = True
                    break
                try:
                    choice = json.loads(chunk)["choices"][0]
                except Exception:                           # noqa: BLE001
                    continue
                delta = choice.get("delta") or {}
                out = {}
                if delta.get("content"):
                    out["content"] = delta["content"]
                if delta.get("reasoning_content"):
                    out["reasoning"] = delta["reasoning_content"]
                if choice.get("finish_reason") == "length":
                    out["warning"] = "Ответ обрезан по лимиту токенов"
                if out:
                    self.wfile.write(sse(out))
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return                                          # клиент ушёл — молча
        except Exception as e:                              # noqa: BLE001
            try:
                self.wfile.write(sse({"error": f"Обрыв потока: {e}"}))
                self.wfile.flush()
            except OSError:
                return
        finally:
            try:
                upstream.close()
            except Exception:                               # noqa: BLE001
                pass
        if not sent_done:
            try:
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except OSError:
                pass


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# --------------------------------------------------------------------------- #
def resolve_port(argv):
    """Приоритет: аргумент командной строки > PORT > 8080."""
    for src in (argv[1] if len(argv) > 1 else None, os.environ.get("PORT")):
        if src:
            try:
                p = int(src)
            except ValueError:
                sys.stderr.write(f"[nimbus] порт {src!r} не число — беру 8080\n")
                continue
            if 1 <= p <= 65535:
                return p
            sys.stderr.write(f"[nimbus] порт {p} вне диапазона — беру 8080\n")
    return 8080


def main(argv=None):
    argv = sys.argv if argv is None else argv
    load_env()
    port = resolve_port(argv)
    host = os.environ.get("HOST", "0.0.0.0")
    key = api_key()
    print(f"[nimbus] Nimbus AI v{VERSION}")
    print(f"[nimbus] API: {base_url()}  ключ: {mask(key) if key else 'НЕ ЗАДАН'}")
    if not key:
        print("[nimbus] ВНИМАНИЕ: создайте .env со строкой DEEPSEEK_API_KEY=sk-...")
    try:
        srv = Server((host, port), Handler)
    except OSError as e:
        sys.stderr.write(f"[nimbus] не удалось занять {host}:{port}: {e}\n")
        return 1
    print(f"[nimbus] слушаю http://{host}:{port}  (Ctrl+C — стоп)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[nimbus] остановлено")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    socket.setdefaulttimeout(None)
    sys.exit(main())
