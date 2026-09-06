#!/usr/bin/env bash
# Nimbus AI — запуск сервера. Использование: bash run.sh [порт]
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Нужен python3. Termux: pkg install python" >&2; exit 1
fi
if [ ! -f ../.env ] && [ ! -f .env ] && [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  echo "⚠️  Не найден .env с DEEPSEEK_API_KEY — чат работать не будет." >&2
  echo "    echo 'DEEPSEEK_API_KEY=sk-...' > $(cd .. && pwd)/.env" >&2
fi
exec python3 server.py "${1:-8080}"
