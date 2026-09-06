#!/usr/bin/env bash
# E2E-дым: реальный сервер Nimbus + mock DeepSeek, проверка через curl.
set -u
cd "$(dirname "$0")/../.."
PORT=${1:-8199}
MOCK=$((PORT + 1))
FAIL=0

check() { # имя, ожидаемая подстрока, вывод
  if printf '%s' "$3" | grep -qF -- "$2"; then echo "  ok  $1"; else
    echo "FAIL  $1 (нет '$2') -> $(printf '%s' "$3" | head -c 200)"; FAIL=1; fi
}

python3 - "$MOCK" <<'PY' &
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def do_GET(self):
        b = json.dumps({"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200); self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close"); self.end_headers()
        for w in ("Nimbus ", "работает"):
            self.wfile.write(("data: " + json.dumps({"choices": [{"delta": {"content": w}}]}) + "\n\n").encode())
        self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush(); self.close_connection = True
ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
PY
MOCK_PID=$!

DEEPSEEK_API_KEY=smoke-key DEEPSEEK_BASE_URL="http://127.0.0.1:$MOCK" \
  HOST=127.0.0.1 python3 nimbus/server.py "$PORT" >/dev/null 2>&1 &
SRV_PID=$!
trap 'kill $MOCK_PID $SRV_PID 2>/dev/null' EXIT

for _ in $(seq 1 40); do curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null && break; sleep 0.2; done

echo "E2E дым-тест на порту $PORT"
check "health"      '"ok": true'    "$(curl -s http://127.0.0.1:$PORT/api/health)"
check "index.html"  'Nimbus AI'     "$(curl -s http://127.0.0.1:$PORT/)"
check "util.js"     'createSSEParser' "$(curl -s http://127.0.0.1:$PORT/util.js)"
check "модели"      'deepseek-reasoner' "$(curl -s http://127.0.0.1:$PORT/api/models)"
OUT=$(curl -s -N -X POST "http://127.0.0.1:$PORT/api/chat" -H 'Content-Type: application/json' \
  -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"тест"}]}')
check "стрим текста" 'работает' "$OUT"
check "стрим [DONE]" '[DONE]'   "$OUT"
check "валидация"    'Пустая история' \
  "$(curl -s -X POST http://127.0.0.1:$PORT/api/chat -H 'Content-Type: application/json' -d '{"messages":[]}')"

[ $FAIL -eq 0 ] && echo "ДЫМ-ТЕСТ ПРОЙДЕН" || echo "ДЫМ-ТЕСТ ПРОВАЛЕН"
exit $FAIL
