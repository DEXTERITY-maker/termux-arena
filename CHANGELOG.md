# Changelog

Все заметные изменения проекта Termux Arena.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
проект придерживается [Semantic Versioning](https://semver.org/lang/ru/).

## [0.0.9] — 2026-08-10

### Added
- Субагенты (ревьюеры, делегации) — видимые tmux-сессии: `scripts/subagent_tmux.sh`
- Панель штурма/субагента держится 10 минут после завершения (итог виден, лог в `~/.hermes/cache/`)

### Fixed
- Маркер согласия: пробел после маркера больше не даёт ложное срабатывание («Итог по теме:»)
- `--resume` по повреждённому JSON сессии сообщает «повреждён файл», а не «не найдена»
- `parse_hermes_session`: первая regex теперь матчит `session_id: <id>`
- `_WEBHOOK_THREADS` очищается от завершённых потоков (UI-режим не копит ссылки)
- Обёртки `arena_sturm.sh`/`subagent_tmux.sh`: каждый аргумент экранируется `printf %q` (`--task "текст с пробелами"`)

## [0.0.8] — 2026-08-10

### Added
- Пассивный интернет: Hermes всегда с тулсетами browser,web, OMP — с инструментами по умолчанию
- Единая постоянная сессия Hermes: создаётся один раз, session_id в `~/arena_hermes_session`, далее `hermes chat --resume <id>`
- Видимый мозговой штурм: `scripts/arena_sturm.sh` — headless в отдельной tmux-сессии `arena-shurm` (не в фоне)

### Changed
- Вебхуки отправляются в daemon-потоке: ход диалога не блокируется
- Маркер согласия распознаётся только в начале ответа («Итог:», «Согласовано:»)
- `session_end` вебхук отправляется после `[EXEC]`
- `--selftest-drop` использует мок моделей вместо реальных вызовов
- Валидация `session_id` в `--resume`/`--session-info` (ровно 8 hex)

### Fixed
- Сессии Hermes больше не плодятся: все вызовы идут в единую сессию
- Ложные срабатывания consensus на подстроках («в итоге я считаю…»)
- Мусорный `~/arena_logs/-.log` при вызове модели без сессии
- `/stop` прерывает паузу между ретраями
- Потеря данных при сбое записи: fsync перед rename
- Сбой `_interrupt` в обработчике больше не маскирует исходное исключение
- Повреждённый JSON сессии сообщается явно, а не как «не найдена»

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
