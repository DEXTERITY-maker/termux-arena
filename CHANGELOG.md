# Changelog

Все заметные изменения проекта Termux Arena.

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
