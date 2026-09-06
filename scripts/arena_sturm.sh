#!/data/data/com.termux/files/usr/bin/bash
# Видимый мозговой штурм арены в отдельной tmux-сессии.
# Требование владельца (Dao, 10.08.2026): штурм НЕ прятать в фоне —
# владелец должен видеть ходы headless в Termux.
#
# Использование:
#   arena_sturm.sh "<тема>" [--turns N] [--consensus] [--task "…"]
#
# Создаёт tmux-сессию arena-shurm (при занятости — arena-shurm-2, -3, …),
# запускает в ней headless-диалог и печатает имя сессии.
# Полный текст итога: tmux capture-pane -t <сессия> -p

TOPIC="$1"; shift
if [ -z "$TOPIC" ]; then
    echo "тема не задана" >&2
    exit 1
fi

BASE="${ARENA_SESS:-arena-shurm}"
SESS="$BASE"
i=2
while tmux has-session -t "$SESS" 2>/dev/null; do
    SESS="${BASE}-$i"
    i=$((i+1))
done

# printf %q — shell-safe кавычки темы и КАЖДОГО аргумента (--task "текст с пробелами")
ARGSQ=""
for a in "$@"; do ARGSQ+="$(printf '%q ' "$a")"; done
CMD="python3 ~/.hermes/arena_chat.py --headless $(printf '%q' "$TOPIC") $ARGSQ; echo; echo '===ШТУРМ ЗАВЕРШЁН (итог выше)==='; sleep 600"
tmux new-session -d -s "$SESS" "$CMD"
echo "штурм запущен: tmux-сессия $SESS (смотреть: tmux attach -t $SESS)"
