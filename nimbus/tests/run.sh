#!/usr/bin/env bash
# Полный прогон тестов Nimbus AI
set -e
cd "$(dirname "$0")/../.."
echo "== Python: сервер =="
python3 nimbus/tests/test_server.py 2>/dev/null
echo
echo "== JS: логика фронтенда =="
if command -v node >/dev/null 2>&1; then node nimbus/tests/test_util.js
else echo "node не найден — пропуск (в Termux: pkg install nodejs)"; fi
