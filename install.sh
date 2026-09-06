#!/data/data/com.termux/files/usr/bin/bash
# install.sh — установка Termux Arena
set -e
cd "$(dirname "$0")"
echo "=== Termux Arena: установка ==="

# 1. Зависимости
echo "[1/5] Базовые зависимости (python, tmux, git, curl)..."
pkg update -y || true
pkg install python tmux git curl -y || true

# 2. Python-модули (версии закреплены в requirements.txt — их проверяет арена при старте)
echo "[2/5] Python-модули (requirements.txt)..."
pip install -r requirements.txt || echo "  ⚠️ pip не смог поставить зависимости — см. Troubleshooting в README"

# 3. Проверка агентов
echo "[3/5] Проверка агентов..."
command -v hermes >/dev/null 2>&1 && echo "  ✅ hermes найден" || echo "  ⚠️ hermes НЕ установлен — арена не сможет вызывать эту модель (см. README)"
command -v omp >/dev/null 2>&1 && echo "  ✅ omp найден" || echo "  ⚠️ omp НЕ установлен — арена не сможет вызывать эту модель (см. README)"

# 4. Скрипты арены → ~/.hermes (обёртки bin/* и scripts/* ищут их именно там)
echo "[4/5] Установка скриптов в ~/.hermes ..."
ARENA_DIR="$HOME/.hermes"
mkdir -p "$ARENA_DIR"
cp arena_chat.py agent_chat.py tg_login.py "$ARENA_DIR/"
chmod +x "$ARENA_DIR/arena_chat.py" "$ARENA_DIR/agent_chat.py" "$ARENA_DIR/tg_login.py"

# 5. Команды-обёртки
echo "[5/5] Установка команд в PATH..."
mkdir -p "$HOME/bin" "$PREFIX/bin"
for f in arena agents; do
  cp "bin/$f" "$HOME/bin/$f" 2>/dev/null || true
  cp "bin/$f" "$PREFIX/bin/$f" 2>/dev/null || true
  chmod +x "$HOME/bin/$f" "$PREFIX/bin/$f" 2>/dev/null || true
done
chmod +x scripts/*.sh 2>/dev/null || true

echo ""
echo "=== Готово! ==="
echo "Запуск: arena        (версия: arena --version)"
echo "Документация: cat README.md"
