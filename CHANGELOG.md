# Changelog

Все заметные изменения проекта Termux Arena.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
проект придерживается [Semantic Versioning](https://semver.org/lang/ru/).

## [0.0.7] — 2026-08-10

### Added
- Протокол v1: сессии в `~/arena_sessions/<id>.json`, атомарная запись после каждого хода
- `--resume <session_id>` — продолжение прерванной сессии
- `--selftest-drop` — автотест обрыва (обрыв → resume → проверка целостности)
- `--session-info <session_id>` — метаданные сессии в JSON
- Лог диалога: `~/arena_logs/<session_id>.log` (`ARENA_LOG_LEVEL=info|debug`)
- Вебхуки событий (start/turn/exec/end/interrupt/resume) на `ARENA_WEBHOOK_URL`, ретраи 1,2,4 с
- Фолбэк-модель OMP: `ARENA_OMP_FALLBACK_MODEL` после 3 ретраев
- `--quiet` — компактный вывод headless

## [0.0.5] — 2026-08-09

### Added
- Единый чат-лог: ходы `[HERMES]` → `[OMP]` → `[HERMES]` в одном потоке
- Автодиалог двух моделей (Hermes ↔ OMP) через CLI-бэкенды
- `/consensus` — диалог до согласия (маркеры с 4-го хода, потолок 30)
- `/task` — дискуссия → исполнение задачи Hermes (`[EXEC]`)
- Доставка итога в основную сессию Hermes (#1) через tmux
- `shell=False` во всех subprocess-вызовах, `--` перед текстом
- Env-конфиг с санитизацией: `ARENA_HOME`, `ARENA_MAIN_SESSION`, `ARENA_OMP_MODEL`, `ARENA_OMP_SYSTEM_PROMPT`
- Версионирование: `--version`, шапка UI и headless-запуска
