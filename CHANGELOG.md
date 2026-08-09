# Changelog

Все заметные изменения проекта Termux Arena.

## [0.0.7] — 2026-08-10

### Added
- Протокол v1: каждая сессия сохраняется в `~/arena_sessions/<id>.json`
  (topic/participants/status/history) после каждого хода, атомарная запись
  (tmp + rename) — восстановление по `session_id` без потерь и дублей
- `--resume <session_id>` — продолжение прерванной сессии (обрыв Termux
  больше не теряет диалог)
- Автотест обрыва `--selftest-drop`: 2 хода → имитация обрыва → resume →
  проверка целостности (номера ходов `[1..4]`, без дублей и потерь)
- Машиночитаемые метаданные: `--session-info <session_id>` (JSON в stdout)
- Полный лог диалога в файл: `~/arena_logs/<session_id>.log`
  (`ARENA_LOG_LEVEL=info|debug`, `--log-level`)
- Вебхуки событий: `session_start` / `turn` / `exec` / `session_end` /
  `session_interrupt` / `session_resume` — POST на `ARENA_WEBHOOK_URL`
  (ретраи 1,2,4 с; `--webhook` для разовой перегрузки)
- Фолбэк-модель OMP: `ARENA_OMP_FALLBACK_MODEL` — попытка после
  `RETRIES=3` с задержкой 2,4,8 с
- `--quiet` — компактный вывод headless (полный текст — в лог-файл)

## [0.0.5] — 2026-08-09

### Initial release
- Единый чат-лог: ходы `[HERMES]` → `[OMP]` → `[HERMES]`… в одном потоке
- Автодиалог двух моделей (Hermes ↔ OMP) через CLI-бэкенды
- `/consensus` — диалог до согласия (детекция маркеров с 4-го хода, потолок 30)
- `/task` — дискуссия → исполнение задачи Hermes (`[EXEC]`-блок)
- Доставка итога в основную сессию Hermes (#1) через tmux
- Безопасность: `shell=False` во всех subprocess-вызовах, `--` перед текстом
- Env-конфиг с санитизацией: `ARENA_HOME`, `ARENA_MAIN_SESSION`,
  `ARENA_OMP_MODEL`, `ARENA_OMP_SYSTEM_PROMPT` (безопасные дефолты, без токенов)
- Версионирование: `--version`, шапка UI и headless-запуска
