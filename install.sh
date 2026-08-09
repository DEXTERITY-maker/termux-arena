#!/data/data/com.termux/files/usr/bin/bash
# install.sh — установка Termux Arena
set -e
echo "=== Termux Arena: установка ==="

# 1. Зависимости
echo "[1/4] Базовые зависимости (python, tmux, git)..."
pkg update -y || true
pkg install python tmux git -y || true

# 2. Python-модули
echo "[2/4] Python-модули (urwid, telethon)..."
pip install urwid telethon || true

# 3. Проверка агентов
echo "[3/4] Проверка агентов..."
command -v hermes >/dev/null 2>&1 && echo "  ✅ hermes найден" || echo "  ⚠️ hermes НЕ установлен — арена не сможет вызывать эту модель (см. README)"
command -v omp >/dev/null 2>&1 && echo "  ✅ omp найден" || echo "  ⚠️ omp НЕ установлен — арена не сможет вызывать эту модель (см. README)"

# 4. Команды-обёртки
echo "[4/4] Установка команд в PATH..."
mkdir -p "$HOME/bin" "$PREFIX/bin"
cp bin/arena "$HOME/bin/arena" 2>/dev/null || true
cp bin/agents "$HOME/bin/agents" 2>/dev/null || true
cp bin/arena "$PREFIX/bin/arena" 2>/dev/null || true
cp bin/agents "$PREFIX/bin/agents" 2>/dev/null || true
chmod +x "$HOME/bin/arena" "$HOME/bin/agents" "$PREFIX/bin/arena" "$PREFIX/bin/agents" 2>/dev/null || true
chmod +x arena_chat.py agent_chat.py tg_login.py 2>/dev/null || true

echo ""
echo "=== Готово! ==="
echo "Запуск: arena"
echo "Документация: cat README.md"
