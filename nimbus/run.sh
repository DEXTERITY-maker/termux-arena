#!/data/data/com.termux/files/usr/bin/env bash
# Запуск Nimbus AI
cd "$(dirname "$0")"
exec python3 server.py "${1:-8080}"
