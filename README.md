# ⚡ Termux Arena — мультиагентный диалог двух моделей

TUI-арена для Termux: **две модели (Hermes и OMP) общаются между собой в едином чат-интерфейсе** — мозговой штурм, дискуссия до согласия, итог с передачей задачи на исполнение. Никаких split-экранов: один общий лог, как обычный чат.

## Возможности
- Единый чат: ходы `[HERMES]` → `[OMP]` → `[HERMES]`… в одном потоке
- `/start <тема>` — запуск диалога; `/turns N` — лимит ходов; `/stop` — мгновенная остановка
- `/consensus` — диалог **до согласия** (арена ловит «договорились/итог» и завершает сама, потолок 30 ходов)
- `/task <задача>` — после дискуссии итог передаётся Hermes на исполнение (`[EXEC]`-блок + доставка в основную сессию Hermes)
- Красивый TUI: рамки ╭─╮, цвета (Hermes — голубой, OMP — пурпурный), статус-бар (ход #N, кто думает)
- Защита: таймауты (120с), анти-зацикливание, проверка exit-кодов

## Требования (новый телефон)
- [Termux](https://f-droid.org/packages/com.termux/) (F-Droid, не Play!)
- Агенты (ставятся отдельно):
  - **Hermes** — `NOUS Hermes` AI Agent Framework (команда `hermes`)
  - **OMP** — `Oh My Pi` v17+ (команда `omp`) — DeepSeek V4 Pro по умолчанию
- Python 3, tmux, git

## Установка
```bash
# 1. Базовые зависимости
pkg update && pkg install python tmux git -y
pip install urwid telethon

# 2. Установи агентов (кратко):
#   Hermes:  запускается командой hermes (см. документацию NOUS Hermes)
#   OMP:     команда omp (Oh My Pi, ставится отдельно)
#   Оба требуют настроенные API-ключи (DeepSeek/OpenRouter и т.п.)

# 3. Клонируй репозиторий
git clone https://github.com/ВАШ_ЛОГИН/termux-arena.git ~/termux-arena
cd ~/termux-arena
bash install.sh

# 4. Запуск
arena
```

## Команды
| Команда | Описание |
|---|---|
| `arena` | интерактивный UI арены |
| `arena --headless "тема" --turns 5` | прогон без UI |
| `arena --headless "тема" --resume <id>` | продолжить прерванную сессию (протокол v1) |
| `arena --session-info <id>` | метаданные сессии (JSON) |
| `arena --selftest-drop` | автотест обрыва сессии |
| `arena --consensus` | диалог до согласия |
| `arena --task "напиши пост по итогам"` | дискуссия → исполнение задачи |
| `arena --smoke` | быстрая самопроверка |
| `bash scripts/arena_sturm.sh "<тема>"` | видимый мозговой штурм: headless в отдельной tmux-сессии `arena-shurm` (ходы видны в Termux, не в фоне) |
| `agents` | меню: Hermes / OMP / Арена |
| `python3 agent_chat.py` | лёгкий 3-панельный монитор (опционально) |

## Структура
```
arena_chat.py          — главный скрипт (движок + UI)
agent_chat.py          — лёгкий 3-панельный монитор сессий
tg_login.py            — вход в Telegram через MTProto (опционально, нужен api_id/api_hash)
bin/arena, bin/agents  — команды-обёртки
scripts/arena_sturm.sh — видимый запуск мозгового штурма в tmux-сессии arena-shurm
docs/plan_arena.md     — план разработки
docs/termux-tracex-content-plan.md — пример контент-плана (шаблон)
```

## Как это работает
Арена вызывает агентов программно (без их TUI):
- Hermes: `hermes chat -q "<промпт>" -Q -t browser,web` — единая постоянная
  сессия: создаётся при первом вызове, session_id в `~/arena_hermes_session`,
  дальше все вызовы — `--resume <id>` (сессии не плодятся)
- OMP: `echo "<промпт>" | omp -p --model deepseek/deepseek-v4-flash`
  (инструменты включены по умолчанию)

Интернет доступен обеим моделям всегда и пассивно: они сами решают, когда
обращаться к сети — переключателей нет. Каждая модель получает историю
диалога, отвечает, ответ передаётся другой — так идёт дискуссия. В режиме
`/consensus` арена распознаёт маркеры завершения («Итог:», «Согласовано:» —
только в начале ответа) и останавливается с итоговым блоком.

## Версии
- Текущая: **v0.0.9** (маркеры согласия, видимые субагенты в tmux, фиксы ревью) — см. [CHANGELOG.md](CHANGELOG.md)
- Проверка версии: `arena --version`
- Обновление: `git pull` в директории репозитория, затем `bash install.sh`
  (при необходимости). Список тегов: `git tag -l`, история: `git log --oneline`

## Лицензия
MIT. Секретов и ключей в репозитории нет — конфигурация агентов хранится в их собственных `~/.hermes/.env` / `~/.omp/.env`.

## Troubleshooting
- **OMP не отвечает (таймаут)** — убедись, что omp установлен и настроен (ключ DeepSeek/OpenRouter). Арена передаёт промпт через stdin: `echo "тест" | omp -p --model deepseek/deepseek-v4-flash`
- **urwid не установлен** — `pip install urwid`
- **tmux: no server running** — Termux убивает фоновые процессы; держи wake-lock: `termux-wake-lock`
- **pip не качает (РФ)** — нужен VPN или зеркало (см. документацию pip)
- **Аренда не видит агентов** — `command -v hermes && command -v omp` должны что-то вернуть

## Чек-лист перед публикацией
- [ ] `grep -rE "bot[0-9]+:|api_hash" .` — нет секретов
- [ ] Gitleaks/trufflehog ДО первого коммита (`gitleaks detect`)
- [ ] `.gitignore` закоммичен ДО любых .env/.session
- [ ] Убраны приватные пути из кода (grep по абсолютным путям)
- [ ] `python3 arena_chat.py --smoke` — работает
