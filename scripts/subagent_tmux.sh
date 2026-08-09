#!/data/data/com.termux/files/usr/bin/bash
# Субагент (ревьюер/делегированная задача) в ОТДЕЛЬНОЙ ВИДИМОЙ tmux-сессии.
# Правило владельца (Dao, 10.08.2026, на постоянку): субагентов НЕ запускать
# в фоне — владелец видит работу каждого субагента в своём окне Termux.
#
# Использование:
#   subagent_tmux.sh <имя> "<задача>" [флаги hermes chat]...
# Пример:
#   subagent_tmux.sh review "Проведи код-ревью: ..." -t terminal,file
#
# Создаёт tmux-сессию subagent-<имя> и запускает в ней:
#   hermes chat -q "<задача>" -Q <флаги> 2>&1 | tee ~/.hermes/cache/subagent-<имя>.log
# После завершения панель держится 10 минут (итог виден), затем сессия закрывается.

NAME="$1"; shift
TASK="$1"; shift
if [ -z "$NAME" ] || [ -z "$TASK" ]; then
    echo "использование: subagent_tmux.sh <имя> \"<задача>\" [флаги hermes chat]" >&2
    exit 1
fi

SAFE=$(printf '%s' "$NAME" | tr -cd 'A-Za-z0-9._-' | sed 's/^-//')
[ -z "$SAFE" ] && SAFE="sub"

BASE="subagent-$SAFE"
SESS="$BASE"
i=2
while tmux has-session -t "$SESS" 2>/dev/null; do
    SESS="${BASE}-$i"
    i=$((i+1))
done

LOG="$HOME/.hermes/cache/subagent-$SAFE.log"
mkdir -p "$HOME/.hermes/cache"
TASKQ=$(printf '%q' "$TASK")
CMD="hermes chat -q $TASKQ -Q $* 2>&1 | tee $LOG; echo; echo '===СУБАГЕНТ ЗАВЕРШЁН (итог выше, лог: $LOG)==='; sleep 600"
tmux new-session -d -s "$SESS" "$CMD"
echo "субагент запущен: tmux-сессия $SESS (смотреть: tmux attach -t $SESS; лог: $LOG)"
